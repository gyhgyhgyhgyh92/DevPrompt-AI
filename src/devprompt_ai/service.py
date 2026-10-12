"""F-001 统一业务入口（双形态唯一，MUST-07/10）。业务判定只在此层与 domain/。"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from devprompt_ai.common.hashing import sha256_hex
from devprompt_ai.common.secrets import mask_secret
from devprompt_ai.config import MODEL_KEY_MAP, AppConfig
from devprompt_ai.domain.decision.followup import GuardrailState, UnknownItem, build_unknowns
from devprompt_ai.domain.decision.port import DecisionPort, VariantScore
from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.generate.ports import GeneratePort, GenerationContext, VariantDraft
from devprompt_ai.domain.generate.variants import expand_levels, resolve_level
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    SessionStore,
    SessionSummary,
    Symbol,
)
from devprompt_ai.domain.ranking.ports import AdoptionRecord, PreferenceStore, VariantLevel
from devprompt_ai.domain.ranking.preference import FEATURE_TABLE, clip01, match_score, update_vector
from devprompt_ai.domain.ranking.recommend import decide_mark
from devprompt_ai.domain.ranking.score import normalize_fit, validate_weights, weighted_total
from devprompt_ai.domain.retrieval.candidates import MAX_CANDIDATES, build_candidates
from devprompt_ai.domain.retrieval.facts import verify_facts
from devprompt_ai.domain.retrieval.locate import locate_symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader
from devprompt_ai.harness.llm import LLMGenerator, last_usage
from devprompt_ai.harness.process import LocalCommandRunner, LocalFileReader, SymbolTableProvider
from devprompt_ai.memory.settings_store import write_model_settings, write_process_settings
from devprompt_ai.observability.logging import emit, emit_error, set_telemetry
from devprompt_ai.state import FlowState, load_or_create, transition

logger = logging.getLogger("devprompt.flow")

Preference = dict[str, float]
SnapshotStatus = Literal["ask", "done", "guardrail"]

_RANK_CACHE_TTL_SECONDS: float = 30.0 * 60.0
"""组件排序缓存 TTL（MUST-14：决策结果 30 分钟；SHOULD-04 惰性淘汰）。"""

_RANK_CACHE: dict[tuple[str, str, str], tuple[float, list[int]]] = {}
"""rank_components 结果缓存（模块级，MUST-14）。

键 = (项目绝对路径, 原句 sha256, 阈值配置 hash)——键不含原句明文；
值 = (过期时刻 monotonic, 候选索引顺序)。禁存原句与决策原始响应。
"""


@dataclass(frozen=True, slots=True)
class RankingView:
    """F-403/F-404 加权推荐视图：字段与 RecommendationResult/加权结果一一对应。

    fit/pref/total 均为 variant 所指档位（最高总分档）的加权明细。
    """

    variant: str
    gap: float
    confidence: float
    marked: bool
    reason: str
    fit: float
    pref: float
    total: float


@dataclass(slots=True)
class FlowSnapshot:
    """表现层快照：CLI/Web 只渲染它（MUST-10）。"""

    session_id: str
    status: SnapshotStatus
    state: str
    questions: list[UnknownItem] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    variants: list[VariantDraft] = field(default_factory=list)
    ranking: RankingView | None = None
    target: Symbol | None = None  # 上下文面板（设计 §1.2）：目标定位 symbol@path:line
    facts: list[FactResult] = field(default_factory=list)  # 取证事实只读透出
    message: str = ""


class ForgeService:
    def __init__(
        self,
        *,
        cfg: AppConfig,
        decider: DecisionPort,
        sessions: SessionStore,
        preferences: PreferenceStore,
        runner: CommandRunner,
        reader: FileReader,
        generator: GeneratePort,
        symbols_provider: SymbolTableProvider,
        symbols_override: list[Symbol] | None = None,
    ) -> None:
        self._cfg = cfg
        self._decider = decider
        self._sessions = sessions
        self._preferences = preferences
        self._runner = runner
        self._reader = reader
        self._generator = generator
        self._symbols_provider = symbols_provider
        self._symbols_override = symbols_override

    async def optimize(
        self, user_id: str, project_root: str, sentence: str, *, request_id: str
    ) -> FlowSnapshot:
        """F-001：创建/恢复会话，执行阶段一至二（检索+探针），路由 ask/done。"""
        session = await load_or_create(self._sessions, user_id)
        try:
            session.data = {
                "sentence": sentence,
                "project_root": project_root,
                "last_request_id": request_id,
                "clarifications": {},
                "rounds": 0,
                "cost_tokens": 0,
                "started_at": time.time(),  # flow.completed 耗时基准（T6-9）
            }
            await transition(session, FlowState.RETRIEVING, self._sessions)
            emit("flow.started", flow_id=session.session_id, request_id=request_id)

            symbols = self._symbols_override
            if symbols is None:
                table = await self._symbols_provider.get(project_root)
                symbols = table.symbols
            result = build_candidates(sentence, symbols)
            session.data["candidates"] = [
                {"name": c.name, "path": c.path, "score": c.score, "source": c.source}
                for c in result.candidates
            ]

            if result.manual_required:
                # slots dataclass 无 __dict__，序列化必须走 asdict（计划 §6.2 注意事项）
                item = UnknownItem(
                    key="manual_target",
                    reason=f"候选不足（{result.total_matched} 条）",
                    best_guess="",
                    ask="请指明目标符号名与文件路径（格式：符号@路径）",
                )
                session.data["unknowns"] = [dataclasses.asdict(item)]
                session.data["level"] = "A"
                await transition(session, FlowState.ASKING, self._sessions)
                return self._snapshot(session, "ask")

            top = await self._rank_top(session, result.candidates)
            symbol = Symbol(name=top.name, path=top.path, line=top.line, kind="function")
            location = await locate_symbol(symbol, self._runner, self._reader, root=project_root)
            facts = await verify_facts(
                location, sentence, self._runner, self._reader, root=project_root
            )
            session.data["facts"] = [
                {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in facts
            ]
            session.data["target"] = {"name": top.name, "path": top.path, "line": top.line}
            await transition(session, FlowState.PROBING, self._sessions)
            return await self._probe_and_route(session, request_id=request_id)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def ask_followup(
        self, user_id: str, session_id: str, answers: dict[str, str], *, request_id: str
    ) -> FlowSnapshot:
        """F-204：批量答复 → 重新研判 → ask/guardrail/done。"""
        session = await self._require(user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING})
        try:
            session.data.setdefault("clarifications", {}).update(answers)
            session.data["last_request_id"] = request_id
            session.data["rounds"] = int(session.data.get("rounds", 0)) + 1
            await transition(session, FlowState.CONFIRMING, self._sessions)
            return await self._reprobe(session)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def resume(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        """--session 恢复入口：只读加载既有会话并重建快照，不做任何状态转移。

        4H 偏差：计划称「service 无需改动」，但 CLI 层不得直读会话存储（只消费快照），
        故以最小只读方法提供恢复路径。
        """
        session = await self._require(
            user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING, FlowState.DONE}
        )
        state = FlowState(session.state)
        if state is FlowState.DONE:
            return self._snapshot(session, "done")
        if state is FlowState.CONFIRMING and session.data.get("guardrail"):
            return self._snapshot(session, "guardrail")
        return self._snapshot(session, "ask")

    async def escape(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        """MUST-26 ②：用户逃生「直接生成」→ 保守版。

        GENERATING 转移统一由 _generate_and_finish 执行（冻结状态机无 GENERATING→GENERATING 边，
        此处不得预转移，否则必抛 6001）。
        """
        session = await self._require(user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING})
        try:
            emit(
                "followup.escaped",
                rounds=session.data.get("rounds", 0),
                request_id=request_id,
            )
            session.data["level"] = "A"
            session.data["conservative"] = True
            return await self._generate_and_finish(session)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FlowSnapshot:
        """MUST-26 ③：软护栏裁决——继续追问（清零）或直接生成。"""
        session = await self._require(user_id, session_id, {FlowState.CONFIRMING})
        try:
            if proceed:
                session.data["rounds"] = 0
                await transition(session, FlowState.ASKING, self._sessions)
                return self._snapshot(session, "ask")
            session.data["level"] = "A"
            session.data["conservative"] = True
            return await self._generate_and_finish(session)
        except Exception:
            await self._abort_quietly(session)
            raise

    async def _abort_quietly(self, session: FlowSession) -> None:
        """失败兜底（6G 遗留①）：异常路径置 ABORTED，避免死会话（如 PROBING）残留污染历史。"""
        try:
            await transition(session, FlowState.ABORTED, self._sessions)
        except Exception:
            logger.exception("state.abort_failed", extra={"session_id": session.session_id})

    async def get_preference(self, user_id: str) -> Preference:
        """L3 偏好向量（F-503）：store 无记录时返回初始中性值（MUST-08：判定在 domain）。"""
        return await self._preferences.load(user_id)

    async def set_preference(self, user_id: str, values: dict[str, float]) -> Preference:
        """PUT /preference 转正（T6-11）：部分更新 + clip01（超界截断而非拒绝），返回更新后向量。"""
        current = await self._preferences.load(user_id)
        merged = dict(current)
        for key, value in values.items():
            if key not in current:
                raise ValueError(f"未知偏好维度：{key}")
            merged[key] = clip01(float(value))
        await self._preferences.save(user_id, merged)
        return merged

    async def clear_adoption_history(self, user_id: str) -> int:
        """清空服务端采纳历史（D-6F-4 关闭）：返回清空条数；偏好向量不动。"""
        return await self._preferences.clear_adoptions(user_id)

    async def list_history(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        """GET /history 转正（T6-11）：脱敏会话摘要（无原句明文，MUST-19）。"""
        return await self._sessions.list_recent(user_id, limit)

    async def rename_session(self, user_id: str, session_id: str, title: str) -> None:
        """PATCH /history/{session_id} 重命名：写 custom_title（截断 ≤80）。

        CAS 冲突（乐观锁 MUST-11）重试一次；仍失败抛 6003。
        """
        clean = title.strip()[:80]
        session = await self._load_owned(user_id, session_id)
        session.data["custom_title"] = clean
        if not await self._sessions.save(session):
            session = await self._load_owned(user_id, session_id)  # 重新加载取新版本
            session.data["custom_title"] = clean
            if not await self._sessions.save(session):
                raise StateError(
                    "会话版本冲突，拒绝写入（乐观锁）",
                    code=6003,
                    context={"session_id": session_id},
                )

    async def pin_session(self, user_id: str, session_id: str, pinned: bool) -> None:
        """PATCH /history/{session_id} 置顶：写 pinned（布尔）；CAS 冲突重试一次后抛 6003。"""
        value = bool(pinned)
        session = await self._load_owned(user_id, session_id)
        session.data["pinned"] = value
        if not await self._sessions.save(session):
            session = await self._load_owned(user_id, session_id)
            session.data["pinned"] = value
            if not await self._sessions.save(session):
                raise StateError(
                    "会话版本冲突，拒绝写入（乐观锁）",
                    code=6003,
                    context={"session_id": session_id},
                )

    async def delete_session(self, user_id: str, session_id: str) -> None:
        """DELETE /history/{session_id}：归属校验后物理删除。"""
        await self._load_owned(user_id, session_id)
        await self._sessions.delete(session_id)

    async def get_settings(self) -> dict[str, Any]:
        """F-604 读设置（T6-11）：有效配置视图（env 已并入）；api_key 恒脱敏，候选上限锁定只读。"""
        cfg = self._cfg
        return {
            "model_service": {
                "provider": cfg.llm_provider,
                "base_url": cfg.llm_base_url,
                "api_key_masked": mask_secret(cfg.llm_api_key),
                "model_id": cfg.llm_model,
                "decider": cfg.decider,
                "timeout": cfg.llm_timeout,
                "temperature": cfg.llm_temperature,
                "max_tokens": cfg.llm_max_tokens,
            },
            "process": {
                "followup_soft_round_guard": cfg.followup_soft_round_guard,
                "followup_cost_budget": cfg.followup_cost_budget,
                "telemetry": cfg.telemetry,
            },
            "locked": {"candidate_limit": MAX_CANDIDATES},  # MUST-09 宪法常量，只读下发
        }

    async def update_settings(self, update: dict[str, Any]) -> dict[str, Any]:
        """PUT /settings（T6-11）：模型段写设置文件（0600）、流程段写 app_settings 表并应用。

        api_key 语义：空值/None = 保持不变；仅显式新值落盘（明文只进设置文件，不进库不进日志）。
        """
        model_in: dict[str, Any] = dict(update.get("model_service") or {})
        process_in: dict[str, Any] = dict(update.get("process") or {})
        api_key = model_in.pop("api_key", None)
        if api_key:  # 非空才替换（空值/None = 不变）
            model_in["api_key"] = api_key
        model_write = {k: v for k, v in model_in.items() if v is not None}
        process_write = {k: v for k, v in process_in.items() if v is not None}
        if model_write:
            await asyncio.to_thread(write_model_settings, model_write)
        if process_write:
            await asyncio.to_thread(write_process_settings, process_write)
        for src_key, value in model_write.items():
            setattr(self._cfg, MODEL_KEY_MAP[src_key], value)
        for key, value in process_write.items():
            setattr(self._cfg, key, value)
        self._cfg.validate()
        set_telemetry(self._cfg.telemetry)
        return await self.get_settings()

    async def feedback(
        self,
        user_id: str,
        session_id: str,
        action: str,
        *,
        request_id: str,
        variant: VariantLevel | None = None,
        edited_text: str | None = None,
    ) -> None:
        """F-603/F-503 采纳反馈写 L3：variant 采纳 / +edited_text 编辑采纳 / 两者皆无=跳过。

        - 采纳/编辑采纳：update_vector（开放决策 #1 定稿合成语义）→ save → record_adoption；
        - 跳过：update_vector(None) 趋向中性 → save（无采纳，不入采纳历史）；
        - store 异常只记日志不上抛：反馈是流程后置信号，不得炸主流程。
        """
        logger.info(
            "feedback.received",
            extra={
                "action": action,
                "user_id": user_id,
                "session_id": session_id,
                "variant": variant,
                "edited": edited_text is not None,
                "request_id": request_id,
            },
        )
        if variant is not None and variant not in FEATURE_TABLE:
            raise ValueError(f"未知方案档位：{variant}")  # 调用方契约错误，快速失败
        try:
            current = await self._preferences.load(user_id)
            if variant is None:
                updated = update_vector(current, None)
                await self._preferences.save(user_id, updated)
            else:
                ratio = 0.0
                if edited_text is not None:
                    # 编辑距离占比 = 1 − SequenceMatcher 相似度（F-503「1 − 编辑距离占比」）
                    ratio = 1.0 - await self._edited_similarity(session_id, edited_text, variant)
                rec = AdoptionRecord(
                    user_id=user_id,
                    session_id=session_id,
                    variant=variant,
                    edited=edited_text is not None,
                    edited_text_ratio=ratio,
                    features=FEATURE_TABLE[variant],
                )
                updated = update_vector(current, rec)
                await self._preferences.save(user_id, updated)
                await self._preferences.record_adoption(rec)
        except Exception:
            logger.exception(
                "feedback.store_failed",
                extra={"session_id": session_id, "request_id": request_id},
            )

    async def scan_project(self, project_root: str) -> dict[str, Any]:
        """F-101 只读统计（Web /project/scan 薄透传）：符号总数/文件数/类别分布。"""
        table = await self._symbols_provider.get(project_root)
        files: set[str] = set()
        kind_counts: dict[str, int] = {}
        for s in table.symbols:
            files.add(s.path)
            kind_counts[s.kind] = kind_counts.get(s.kind, 0) + 1
        ranked = dict(sorted(kind_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        return {
            "total_symbols": len(table.symbols),
            "total_files": len(files),
            "kind_counts": ranked,
        }

    # ---- 内部 ----

    async def _edited_similarity(self, session_id: str, edited_text: str, variant: str) -> float:
        """编辑相似度：difflib.SequenceMatcher.ratio（标准库，MUST-04）。

        以会话内被采纳档位的方案正文为基准（采纳必须绑定档位，variant 恒非空）；
        档位缺失时会话/方案按 0 相似度处理（无法核对编辑来源 → 编辑距离占比 1.0
        → 零方向信号，不误更新偏好）。
        """
        session = await self._sessions.load(session_id)
        original = ""
        if session is not None:
            items = [v for v in session.data.get("variants", []) if isinstance(v, dict)]
            chosen = next((v for v in items if v.get("level") == variant), None)
            if chosen is None and items:
                chosen = items[0]
            if chosen is not None:
                original = str(chosen.get("body", ""))
        return difflib.SequenceMatcher(None, original, edited_text).ratio()

    async def _probe_and_route(self, session: FlowSession, *, request_id: str) -> FlowSnapshot:
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        probe = await self._decider.probe_facts(session.data["sentence"], facts)
        session.data["probe_confidence"] = probe.overall_confidence
        unknowns = build_unknowns(probe, facts, clarifications=session.data.get("clarifications"))
        session.data["unknowns"] = [dataclasses.asdict(u) for u in unknowns]
        facts_complete = (
            bool(facts)
            and all(f.passed for f in facts)
            and probe.overall_confidence >= self._cfg.fact_probe_threshold
        )
        has_symbol = bool(session.data.get("target"))
        session.data["level"] = resolve_level(has_symbol=has_symbol, facts_complete=facts_complete)
        if unknowns:
            await transition(session, FlowState.ASKING, self._sessions)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session)

    async def _reprobe(self, session: FlowSession) -> FlowSnapshot:
        """F-204：答复后重新研判（取证结果不变，clarifications 已更新）。"""
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        probe = await self._decider.probe_facts(session.data["sentence"], facts)
        unknowns = build_unknowns(probe, facts, clarifications=session.data.get("clarifications"))
        session.data["unknowns"] = [dataclasses.asdict(u) for u in unknowns]
        guard = GuardrailState(
            rounds=int(session.data.get("rounds", 0)),
            cost_tokens=int(session.data.get("cost_tokens", 0)),
        )
        if guard.should_trigger(self._cfg):
            emit(
                "followup.guardrail",
                rounds=guard.rounds,
                cost_tokens=guard.cost_tokens,
                request_id=session.data.get("last_request_id", ""),
            )
            return self._snapshot(session, "guardrail")  # 停在 CONFIRMING 等裁决（6002 语义）
        if unknowns:
            await transition(session, FlowState.ASKING, self._sessions)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session)

    async def _generate_and_finish(self, session: FlowSession) -> FlowSnapshot:
        """GENERATING→(RANKING)→DONE：三套同调生成 + 加权推荐（5F，BREAKING）。

        状态机：≥2 套（B/C 档）经 RANKING 打分与判定后 DONE；仅 1 套（A 档
        escape/保守路径）按 MUST-28 跳过打分与推荐（不计算 d），直接 GENERATING→DONE。
        """
        await transition(session, FlowState.GENERATING, self._sessions)
        ctx = GenerationContext(
            sentence=session.data["sentence"],
            project_root=session.data["project_root"],
            level=session.data.get("level", "A"),
            facts_summary=session.data.get("facts_summary", _summarize_facts(session)),
            clarifications=session.data.get("clarifications", {}),
            conservative=bool(session.data.get("conservative", False)),
        )
        multi = await self._generator.generate_variants(ctx, expand_levels(ctx.level))
        usage = last_usage()
        if usage:
            session.data["cost_tokens"] = (
                int(session.data.get("cost_tokens", 0)) + usage["total_tokens"]
            )
        # slots dataclass 无 __dict__，序列化必须走 model_dump（计划 §6.2 注意事项）
        session.data["variants"] = [v.model_dump() for v in multi.variants]
        if len(multi.variants) < 2:
            # MUST-28：单套（仅 A 档）跳过打分与推荐，ranking=None，不计算 d
            emit(
                "recommendation.skipped",
                reason="single-variant",
                gap=None,
                confidence=None,
                request_id=session.data.get("last_request_id", ""),
            )
            await transition(session, FlowState.DONE, self._sessions)
            self._emit_completed(session, variants=len(multi.variants), marked=None)
            return self._snapshot(session, "done")
        await transition(session, FlowState.RANKING, self._sessions)
        ranking = await self._rank_and_mark(session, multi.variants)
        session.data["ranking"] = dataclasses.asdict(ranking) if ranking is not None else None
        await transition(session, FlowState.DONE, self._sessions)
        self._emit_completed(
            session,
            variants=len(multi.variants),
            marked=ranking.marked if ranking is not None else None,
        )
        return self._snapshot(session, "done")

    def _emit_completed(self, session: FlowSession, *, variants: int, marked: bool | None) -> None:
        """flow.completed（T6-9）：耗时 = 会话起点至生成收尾（跨反问轮次的真实全程）。"""
        started_at = float(session.data.get("started_at", 0.0))
        elapsed_ms = int((time.time() - started_at) * 1000) if started_at else None
        emit(
            "flow.completed",
            flow_id=session.session_id,
            variants=variants,
            marked=marked,
            elapsed_ms=elapsed_ms,
            request_id=session.data.get("last_request_id", ""),
        )

    async def _rank_and_mark(
        self, session: FlowSession, variants: list[VariantDraft]
    ) -> RankingView | None:
        """F-401~404 RANKING 态编排：score_prompts → 归一化 → 匹配度 → 加权总分 → 判定。

        决策层任何异常（LLM 故障/输出缺档位）→ 诚实降级 ranking=None 不阻断流程
        （宁缺勿假，比崩溃好）；不缓存三套方案正文与决策原始响应（MUST-14）。
        """
        w_fit = self._cfg.prefer_adapt_weight
        w_pref = self._cfg.prefer_history_weight
        request_id = session.data.get("last_request_id", "")
        try:
            validate_weights(w_fit, w_pref)
            context = str(session.data.get("facts_summary") or _summarize_facts(session))
            scores = await self._decider.score_prompts(
                context, [(v.level, v.body) for v in variants]
            )
            by_level = {s.variant: s for s in scores.scores}
            pref = await self._preferences.load(session.user_id)
            entries: list[tuple[VariantScore, float]] = []
            details: dict[str, tuple[float, float, float]] = {}
            for v in variants:
                score = by_level[v.level]
                fit = normalize_fit(score.score)
                pref_match = match_score(pref, FEATURE_TABLE[v.level])
                total = weighted_total(fit, pref_match, w_fit, w_pref)
                entries.append((score, total))
                details[v.level] = (fit, pref_match, total)
            rec = decide_mark(entries)
        except Exception:
            emit_error(
                "recommendation.skipped",
                reason="score-failed",
                gap=None,
                confidence=None,
                request_id=request_id,
            )
            return None
        top_fit, top_pref, top_total = details[rec.variant]
        emit(
            "recommendation.made" if rec.marked else "recommendation.skipped",
            gap=rec.gap,
            confidence=rec.confidence,
            marked=rec.marked,
            variant=rec.variant,
            reason=rec.reason,
            request_id=request_id,
        )
        return RankingView(
            variant=rec.variant,
            gap=rec.gap,
            confidence=rec.confidence,
            marked=rec.marked,
            reason=rec.reason,
            fit=top_fit,
            pref=top_pref,
            total=top_total,
        )

    async def _rank_top(self, session: FlowSession, candidates: list[Candidate]) -> Candidate:
        """RETRIEVING 段组件排序（MUST-09 顺序：候选 ≤25 已压好，此处只排序取 top1）。

        命中缓存（同项目+同原句+同阈值配置）则不调决策层；失败/空序降级回
        candidates[0]（排序失败不阻断检索主链）；失败结果不缓存（避免 30 分钟固化降级）。
        """
        sentence = str(session.data["sentence"])
        project_root = str(session.data["project_root"])
        request_id = session.data.get("last_request_id", "")
        key = (project_root, sha256_hex(sentence), _threshold_hash(self._cfg))
        now = time.monotonic()
        cached = _RANK_CACHE.get(key)
        if cached is not None:
            expires_at, order = cached
            if now <= expires_at and order and order[0] < len(candidates):
                emit("cache.hit", request_id=request_id, candidates=len(candidates))
                return candidates[order[0]]
            _RANK_CACHE.pop(key, None)  # 过期惰性淘汰（SHOULD-04）
        emit("cache.miss", request_id=request_id, candidates=len(candidates))
        try:
            out = await self._decider.rank_components(sentence, candidates)
        except Exception:
            logger.exception(
                "ranking.rank_failed",
                extra={"reason": "decider-failed", "request_id": request_id},
            )
            return candidates[0]
        _RANK_CACHE[key] = (now + _RANK_CACHE_TTL_SECONDS, list(out.order))
        if out.order and out.order[0] < len(candidates):
            return candidates[out.order[0]]
        return candidates[0]

    def _snapshot(self, session: FlowSession, status: SnapshotStatus) -> FlowSnapshot:
        questions = [UnknownItem(**u) for u in session.data.get("unknowns", [])]
        ranking_data = session.data.get("ranking")
        target_data = session.data.get("target")
        target = (
            Symbol(
                name=str(target_data["name"]),
                path=str(target_data["path"]),
                line=int(target_data.get("line", 0)),
                kind="function",
            )
            if isinstance(target_data, dict)
            else None
        )
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        return FlowSnapshot(
            session_id=session.session_id,
            status=status,
            state=session.state,
            questions=questions,
            cleared=sorted(session.data.get("clarifications", {}).keys()),
            variants=[VariantDraft(**v) for v in session.data.get("variants", [])],
            ranking=RankingView(**ranking_data) if isinstance(ranking_data, dict) else None,
            target=target,
            facts=facts,
        )

    async def _load_owned(self, user_id: str, session_id: str) -> FlowSession:
        """归属校验（不限定状态，区别于 _require）：不存在/非本人抛 6003。"""
        session = await self._sessions.load(session_id)
        if session is None or session.user_id != user_id:
            raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
        return session

    async def _require(self, user_id: str, session_id: str, allowed: set[FlowState]) -> FlowSession:
        session = await self._sessions.load(session_id)
        if session is None or session.user_id != user_id:
            raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
        if FlowState(session.state) not in allowed:
            raise StateError(
                f"当前状态 {session.state} 不允许该操作",
                code=6001,
                context={"session_id": session_id, "state": session.state},
            )
        return session


def _summarize_facts(session: FlowSession) -> str:
    parts = [
        f"{f['key']}={'真' if f['passed'] else '假'}（{f['evidence'][:80]}）"
        for f in session.data.get("facts", [])
    ]
    target = session.data.get("target", {})
    return f"目标：{target.get('name', '')}@{target.get('path', '')}；" + "；".join(parts)


def _threshold_hash(cfg: AppConfig) -> str:
    """MUST-14 缓存键影响因子：prefer_* 阈值配置的 json 序列化 sha256。

    阈值调整 → hash 变化 → 缓存失效，杜绝读到旧阈值下的排序结果；
    仅摘要入键，不落原句明文（MUST-14 禁缓存项）。
    """
    payload = json.dumps(
        {
            "prefer_adapt_weight": cfg.prefer_adapt_weight,
            "prefer_history_weight": cfg.prefer_history_weight,
            "prefer_hard_threshold": cfg.prefer_hard_threshold,
            "prefer_soft_threshold": cfg.prefer_soft_threshold,
            "prefer_min_confidence": cfg.prefer_min_confidence,
            "prefer_low_confidence": cfg.prefer_low_confidence,
        },
        sort_keys=True,
    )
    return sha256_hex(payload)


async def build_default(cfg: AppConfig) -> ForgeService:
    """默认组装（CLI/开发态；Web 复用同一函数，MUST-10）。"""
    from devprompt_ai.decision.fallback import create_decider
    from devprompt_ai.memory.preference_store import SQLitePreferenceStore
    from devprompt_ai.memory.session_store import SQLiteSessionStore

    sessions = SQLiteSessionStore(cfg.db_path)
    await sessions.init_schema()
    preferences = SQLitePreferenceStore(cfg.db_path)
    await preferences.init_schema()
    return ForgeService(
        cfg=cfg,
        decider=create_decider(cfg),
        sessions=sessions,
        preferences=preferences,
        runner=LocalCommandRunner(),
        reader=LocalFileReader(),
        generator=LLMGenerator(cfg),
        symbols_provider=SymbolTableProvider(LocalCommandRunner()),
    )
