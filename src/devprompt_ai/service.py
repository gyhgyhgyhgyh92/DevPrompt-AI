"""F-001 统一业务入口（双形态唯一，MUST-07/10）。业务判定只在此层与 domain/。"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from devprompt_ai.common.cost import take_llm_tokens
from devprompt_ai.common.hashing import sha256_hex
from devprompt_ai.common.process import ProcessError
from devprompt_ai.common.secrets import mask_secret
from devprompt_ai.config import MODEL_KEY_MAP, AppConfig
from devprompt_ai.domain.context import (
    ContextBudget,
    ContextPayload,
    TurnInput,
    TurnSummary,
    build_context,
    summary_from_turn,
)
from devprompt_ai.domain.decision.followup import (
    GuardrailState,
    UnknownItem,
    UnknownOption,
    build_unknowns,
    lint_questions,
)
from devprompt_ai.domain.decision.port import DecisionPort, FactProbeOutput, VariantScore
from devprompt_ai.domain.errors import (
    CatalogFetchError,
    ConfigurationError,
    DevPromptError,
    StateError,
)
from devprompt_ai.domain.generate.ports import GeneratePort, GenerationContext, VariantDraft
from devprompt_ai.domain.generate.variants import plan_levels, resolve_level
from devprompt_ai.domain.model_catalog import (
    ModelCatalogFetcher,
    ModelCatalogItem,
    effective_context_window,
    mark_stale_models,
    merge_catalog,
    static_catalog,
)
from devprompt_ai.domain.model_spec import (
    providers_projection,
    resolve_api_mode,
    resolve_provider_key,
)
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    ProjectNoteStore,
    SessionStore,
    SessionSummary,
    Symbol,
    TurnRecord,
    TurnStore,
)
from devprompt_ai.domain.progress import (
    ProgressEvent,
    ProgressSink,
    candidates_text,
    clarification_text,
    facts_text,
    generation_text,
    level_text,
    manual_required_text,
    recommendation_text,
    retrieval_text,
    scoring_text,
    single_variant_text,
    symbols_text,
    target_text,
)
from devprompt_ai.domain.ranking.recommend import decide_mark
from devprompt_ai.domain.ranking.score import normalize_fit, weighted_total
from devprompt_ai.domain.retrieval.candidates import MAX_CANDIDATES, build_candidates
from devprompt_ai.domain.retrieval.facts import verify_facts
from devprompt_ai.domain.retrieval.locate import locate_symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader
from devprompt_ai.harness.llm import LLMGenerator, last_usage
from devprompt_ai.harness.process import LocalCommandRunner, LocalFileReader, SymbolTableProvider
from devprompt_ai.harness.trace import TracingReader, TracingRunner
from devprompt_ai.memory.model_catalog_store import read_model_catalog, write_model_catalog
from devprompt_ai.memory.project_note_store import normalize_key
from devprompt_ai.memory.settings_store import (
    read_model_registry,
    write_model_registry,
    write_model_settings,
    write_process_settings,
)
from devprompt_ai.memory.turn_store import TurnConflictError
from devprompt_ai.observability.logging import emit, emit_error, emit_warning, set_telemetry
from devprompt_ai.state import FlowState, start_turn, transition

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


async def _notify(session: FlowSession, progress: ProgressSink | None, text: str) -> None:
    """推送一条思考文案（带当前阶段）。进度是尽力而为：失败绝不影响业务流程。"""
    if progress is None:
        return
    try:
        await progress.emit(ProgressEvent(text=text, phase=session.state))
    except Exception:
        logger.debug("progress.emit_failed", exc_info=True)


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
    total: float


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """F-805 成本明细：单次优化 token 用量（LLM 实际用量）。

    llm_tokens 为 SDK 实际用量；total_tokens 即 llm_tokens 合计
    （2026-10-15 起决策层为单一 LLM 实现，用量同源）。
    """

    llm_tokens: int
    total_tokens: int
    llm_source: str


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
    cost: CostBreakdown | None = None  # F-805：token 用量明细（LLM）
    message: str = ""


#: 用户表达方向性分歧的信号词（启发式，不调 LLM）：命中则本轮重新给三套。
#: shortcut: 只覆盖常见说法，未命中时沿用上一轮选定方向（省 token），需要更准可换 LLM 判定。
_DIRECTION_CONFLICT_WORDS: tuple[str, ...] = (
    "推翻",
    "不要按",
    "换个方向",
    "换成另一种",
    "重新考虑",
    "走激进",
    "保守一点",
    "别用刚才",
)


def _preferred_level(session: FlowSession) -> Literal["A", "B", "C"] | None:
    """上一轮选定的档位（非 A/B/C 的脏数据一律忽略）。"""
    value = str(session.data.get("preferred_level", ""))
    if value == "A":
        return "A"
    if value == "B":
        return "B"
    if value == "C":
        return "C"
    return None


def _unknown_from(raw: dict[str, Any]) -> UnknownItem:
    """会话里存的未知项（dict，options 已被 asdict 展开）→ domain 对象。"""
    return UnknownItem(
        key=str(raw.get("key", "")),
        reason=str(raw.get("reason", "")),
        best_guess=str(raw.get("best_guess", "")),
        ask=str(raw.get("ask", "")),
        header=str(raw.get("header", "")),
        options=tuple(
            UnknownOption(
                label=str(option.get("label", "")), description=str(option.get("description", ""))
            )
            for option in raw.get("options", [])
            if isinstance(option, dict)
        ),
        multi_select=bool(raw.get("multi_select", False)),
    )


def _catalog_item_view(item: ModelCatalogItem) -> dict[str, Any]:
    """目录条目 → 契约视图（tiers 转 list；字段名与 `ModelCatalogItem` 契约一致）。"""
    return {
        "model_id": item.model_id,
        "label": item.label,
        "max_context_length": item.max_context_length,
        "context_window_tiers": list(item.context_window_tiers),
        "reasoning_efforts": list(item.reasoning_efforts),
        "default_effort": item.default_effort,
        "source": item.source,
        "is_stale": item.is_stale,
    }


class ForgeService:
    def __init__(
        self,
        *,
        cfg: AppConfig,
        decider: DecisionPort,
        sessions: SessionStore,
        runner: CommandRunner,
        reader: FileReader,
        generator: GeneratePort,
        symbols_provider: SymbolTableProvider,
        catalog_fetcher: ModelCatalogFetcher | None = None,
        symbols_override: list[Symbol] | None = None,
        turns: TurnStore | None = None,
        notes: ProjectNoteStore | None = None,
    ) -> None:
        self._cfg = cfg
        self._decider = decider
        self._sessions = sessions
        #: 多轮 turn 存储；None 时跳过双写（旧测试零改动）
        self._turns = turns
        #: L2 项目记忆；None 时不注入也不记录
        self._notes = notes
        self._runner = runner
        self._reader = reader
        self._generator = generator
        self._symbols_provider = symbols_provider
        self._catalog_fetcher = catalog_fetcher
        self._symbols_override = symbols_override

    # ------------------------------------------------------------------
    # 模型目录（2026-10-17 动态模型目录）
    # ------------------------------------------------------------------

    def provider_catalog_target(
        self, provider_id: str, *, with_key: bool = False
    ) -> tuple[str, str, str]:
        """按供应商 id 取出拉取模型目录所需的 provider / base_url / api_key。

        2026-10-18 供应商中心化重构：目录挂在**供应商**（端点+密钥）而非条目上——
        刚配好、还没勾选任何模型的供应商也必须能刷新（多选流程的第一步）。

        **api_key 只从 settings.json（0600）读、当场返回给调用方**，不写库、不进日志
        （MUST-19）。供应商不存在时抛 :class:`StateError`（非法引用，明确拒绝而非静默）。
        """
        for record in read_model_registry()["providers"]:
            if str(record.get("id", "")) != provider_id:
                continue
            provider = str(record.get("provider", ""))
            base_url = str(record.get("base_url", ""))
            if not base_url.strip():
                raise ConfigurationError(
                    f"供应商 {provider_id} 未填写接口地址，无法拉取模型列表",
                    context={"provider_id": provider_id, "provider": provider},
                )
            return provider, base_url, (str(record.get("api_key", "")) if with_key else "")
        raise StateError(f"供应商不存在：{provider_id}", context={"provider_id": provider_id})

    def _catalog_key(self, provider: str, base_url: str) -> tuple[str, str]:
        """目录缓存键 = (规范 provider key, 端点)。同一厂商换端点即另一份缓存。"""
        return resolve_provider_key(provider), base_url.strip()

    def _configured_model_ids(self, provider: str) -> list[str]:
        """该厂商下用户已配置的 model_id（用于标注「不在当前列表」）。"""
        registry = read_model_registry()
        return [
            str(entry.get("model_id", ""))
            for entry in registry["models"]
            if resolve_provider_key(str(entry.get("provider", "")))
            == resolve_provider_key(provider)
        ]

    async def read_model_catalog(
        self, provider: str, base_url: str, *, request_id: str
    ) -> dict[str, Any]:
        """读模型目录（落库快照；无记录则回落静态表）。

        **不联网**——读的是上次刷新结果。联网拉取是 :meth:`refresh_model_catalog`。
        """
        provider_key, url = self._catalog_key(provider, base_url)
        items, fetched_at = await asyncio.to_thread(read_model_catalog, provider_key, url)
        if not items:
            items = static_catalog(provider)
        items = mark_stale_models(items, self._configured_model_ids(provider), provider=provider)
        return {
            "provider": provider_key,
            "base_url": url,
            "fetched_at": fetched_at,
            "models": [_catalog_item_view(item) for item in items],
            "warning": None,
        }

    async def refresh_model_catalog(
        self, provider: str, base_url: str, api_key: str, *, request_id: str
    ) -> dict[str, Any]:
        """刷新模型目录：现场拉取 → 落库 → 返回合并结果。

        **拉取失败不清空**：返回上次落库的快照 + ``warning`` 说明失败原因
        （用户裁定：限流不该让已配模型失效）。快照也没有时回落静态表。
        """
        provider_key, url = self._catalog_key(provider, base_url)
        warning: str | None = None
        items: list[ModelCatalogItem] = []
        fetched_at: str | None = None

        if self._catalog_fetcher is None:
            warning = "当前构建未接入模型目录拉取器（catalog_fetcher 未注入）"
        else:
            try:
                remote = await self._catalog_fetcher.fetch(
                    base_url=url, api_key=api_key, timeout=self._cfg.llm_timeout
                )
                merged = merge_catalog(
                    remote, provider=provider, static_items=static_catalog(provider)
                )
                if merged:
                    items = merged
                    fetched_at = await asyncio.to_thread(
                        write_model_catalog, provider_key, url, merged
                    )
                    emit(
                        "model_catalog.refreshed",
                        provider=provider_key,
                        count=len(merged),
                        request_id=request_id,
                    )
                else:
                    warning = "该端点未返回任何可用模型，已保留上次结果"
            except CatalogFetchError as exc:
                warning = str(exc)
                emit_error(
                    "model_catalog.refresh_failed", provider=provider_key, request_id=request_id
                )

        if not items:
            cached, cached_at = await asyncio.to_thread(read_model_catalog, provider_key, url)
            items, fetched_at = cached, cached_at
        if not items:
            items = static_catalog(provider)
            fetched_at = None

        items = mark_stale_models(items, self._configured_model_ids(provider), provider=provider)
        return {
            "provider": provider_key,
            "base_url": url,
            "fetched_at": fetched_at,
            "models": [_catalog_item_view(item) for item in items],
            "warning": warning,
        }

    def effective_window(
        self, provider: str, model_id: str, selected_tier: int | None
    ) -> int | None:
        """生效窗口（动态优先）；读落库快照，不联网。

        供 ``_registry_view`` 与激活条目回填共用，确保「界面显示的档位」与
        「告警实际用的窗口」永远来自同一条回落链（MUST-08 单一来源）。
        """
        base_url = ""
        for entry in read_model_registry()["models"]:
            if resolve_provider_key(str(entry.get("provider", ""))) == resolve_provider_key(
                provider
            ):
                base_url = str(entry.get("base_url", ""))
                break
        items, _ = read_model_catalog(*self._catalog_key(provider, base_url))
        return effective_context_window(provider, model_id, selected_tier, items)

    def _traced(
        self,
        progress: ProgressSink | None,
        root: str,
        phase: Callable[[], str] | None = None,
    ) -> tuple[CommandRunner, FileReader]:
        """按请求包装观测层：真实 rg / 读文件会上报成动作卡片。

        ``progress`` 缺省时返回原实例（旧调用方零改动）；包装器不挂单例状态，
        并发请求各持一份，不会串台。
        """
        if progress is None:
            return self._runner, self._reader
        return (
            TracingRunner(self._runner, progress, root, phase),
            TracingReader(self._reader, progress, root, phase),
        )

    async def optimize(
        self,
        user_id: str,
        project_root: str,
        sentence: str,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
        session_id: str | None = None,
    ) -> FlowSnapshot:
        """F-001：创建/恢复会话，执行阶段一至二（检索+探针），路由 ask/done。

        ``progress`` 为可选的思考过程出口（流式端点传入）；缺省 None 时旧调用方零改动。
        ``session_id`` 非空表示**在同一会话开启新一轮**（多轮，2026-10-20）。
        """
        session = await start_turn(self._sessions, user_id, session_id)
        try:
            # 多轮：本轮可以只给原句，项目路径沿用它所在会话的既有值
            project_root = project_root or str(session.data.get("project_root", ""))
            if not project_root:
                raise DevPromptError("项目路径不能为空", code=2001)
            # 上一轮的结论与完备度（决定本轮给几套；data 随后会被整体重置）
            previous_summary: dict[str, Any] = {}
            if self._turns is not None:
                records = await self._turns.list_for_session(session.session_id)
                if records and isinstance(records[-1].summary, dict):
                    previous_summary = records[-1].summary
            # 轮次序号跨轮累积（session.data 会被本轮整体重置，故先取出再写回）
            previous_index = int(session.data.get("turn_index", -1))
            session.data = {
                "sentence": sentence,
                "project_root": project_root,
                "last_request_id": request_id,
                "clarifications": {},
                "rounds": 0,
                "cost_tokens": 0,  # 总 token（护栏判定用，MUST-26 成本预算）
                "cost_llm_tokens": 0,  # F-805：LLM 实际用量
                "started_at": time.time(),  # flow.completed 耗时基准（T6-9）
                "turn_index": previous_index,
                "preferred_level": str(previous_summary.get("decision", "")),
                "prev_facts_complete": previous_summary.get("facts_complete"),
            }
            await self._begin_turn(session)
            await transition(session, FlowState.RETRIEVING, self._sessions)
            emit("flow.started", flow_id=session.session_id, request_id=request_id)
            await _notify(session, progress, retrieval_text())

            symbols = self._symbols_override
            if symbols is None:
                table = await self._symbols_provider.get(project_root)
                symbols = table.symbols
            await _notify(session, progress, symbols_text(len(symbols)))
            result = build_candidates(sentence, symbols)
            await _notify(
                session, progress, candidates_text(result.total_matched, len(result.candidates))
            )
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
                await _notify(session, progress, manual_required_text(result.total_matched))
                await transition(session, FlowState.ASKING, self._sessions)
                await self._finish_turn(session)
                return self._snapshot(session, "ask")

            top = await self._rank_top(session, result.candidates)
            symbol = Symbol(name=top.name, path=top.path, line=top.line, kind="function")
            runner, reader = self._traced(progress, project_root, lambda: session.state)
            location = await locate_symbol(symbol, runner, reader, root=project_root)
            await _notify(
                session, progress, target_text(top.name, top.path, location.definition_line)
            )
            facts = await verify_facts(location, sentence, runner, reader, root=project_root)
            await _notify(
                session, progress, facts_text(sum(1 for f in facts if f.passed), len(facts))
            )
            session.data["facts"] = [
                {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in facts
            ]
            session.data["target"] = {"name": top.name, "path": top.path, "line": top.line}
            await transition(session, FlowState.PROBING, self._sessions)
            return await self._probe_and_route(session, request_id=request_id, progress=progress)
        except asyncio.CancelledError:
            # 客户端断流：CancelledError 属 BaseException，下面的 except Exception 抓不到
            await self._abort_quietly(session)
            raise
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
                await self._finish_turn(session)
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

    async def list_history(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        """GET /history 转正（T6-11）：脱敏会话摘要（无原句明文，MUST-19）。"""
        return await self._sessions.list_recent(user_id, limit)

    async def list_turns(self, user_id: str, session_id: str) -> list[TurnRecord]:
        """会话的轮次摘要（按 turn_index 升序）；归属不符抛 6003。"""
        await self._load_owned(user_id, session_id)
        if self._turns is None:
            return []
        return await self._turns.list_for_session(session_id)

    async def load_turn(self, user_id: str, turn_id: str) -> TurnRecord:
        """单轮全文（懒加载用）；不存在或非本人抛 6003。"""
        record = None if self._turns is None else await self._turns.load(turn_id)
        if record is None:
            raise StateError("轮次不存在", code=6003, context={"turn_id": turn_id})
        await self._load_owned(user_id, record.session_id)
        return record

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

    def _registry_view(self) -> list[dict[str, Any]]:
        """注册表脱敏视图（F-604 多模型）：api_key 恒脱敏；is_active 由激活位比对得出。

        2026-09-17 模型管理迁移：增 `capabilities` 只读字段，
        供设置中心渲染能力徽标与参数编辑器。两者已在读侧归一化，此处只做脱敏与透出。
        """
        registry = read_model_registry()
        active_id = registry["active_model_id"]
        views: list[dict[str, Any]] = []
        for entry in registry["models"]:
            entry_id = str(entry.get("id", ""))
            capabilities = entry.get("capabilities")
            views.append(
                {
                    "id": entry_id,
                    "provider_id": str(entry.get("provider_id", "")),
                    "provider": str(entry.get("provider", "")),
                    "model_id": str(entry.get("model_id", "")),
                    "is_active": entry_id == active_id,
                    "capabilities": dict(capabilities) if isinstance(capabilities, dict) else {},
                    "api_mode": str(entry.get("api_mode", "") or ""),
                    "reasoning_effort": str(entry.get("reasoning_effort", "") or ""),
                    "max_context_length": entry.get("max_context_length"),
                }
            )
        return views

    @staticmethod
    def _provider_configs_view() -> list[dict[str, Any]]:
        """供应商配置脱敏视图（2026-10-18 供应商中心化）：api_key 恒脱敏（MUST-19）。"""
        return [
            {
                "id": str(record.get("id", "")),
                "provider": str(record.get("provider", "")),
                "base_url": str(record.get("base_url", "")),
                "api_key_masked": mask_secret(str(record.get("api_key", ""))),
            }
            for record in read_model_registry()["providers"]
        ]

    @staticmethod
    def _merge_provider_configs(
        incoming: list[dict[str, Any]], existing: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """供应商**权威列表**归并：id 缺省生成（p- + uuid）；api_key 空则沿用旧值。

        绝不做深合并——否则用户删掉的供应商会被「礼貌地」保留回来。

        密钥回落两级：①同 id 旧记录；②**同 (provider, base_url) 的旧记录**。
        第二级是安全网：前端会为新供应商自行生成 id，一旦 id 对不上而密钥又没填，
        只靠①会把密钥静默清空——而同一端点的凭据本就是同一份。
        """
        by_id = {str(e.get("id")): e for e in existing if e.get("id")}
        # 同端点索引：安全网，见 docstring 第二级回落
        by_endpoint = {
            (str(e.get("provider") or "").strip().lower(), str(e.get("base_url") or "").strip()): e
            for e in existing
        }
        merged: list[dict[str, Any]] = []
        for raw in incoming:
            record_id = str(raw.get("id") or "").strip() or f"p-{uuid.uuid4().hex[:8]}"
            provider = str(raw.get("provider") or "").strip()
            base_url = str(raw.get("base_url") or "").strip()
            old = by_id.get(record_id) or by_endpoint.get((provider.lower(), base_url))
            api_key = raw.get("api_key")
            # 空值/None = 沿用同 id 旧值：前端只有脱敏值，回传空串是常态
            if api_key in (None, ""):
                api_key = str((old or {}).get("api_key", ""))
            merged.append(
                {
                    "id": record_id,
                    "provider": provider,
                    "base_url": base_url,
                    "api_key": str(api_key or ""),
                }
            )
        return merged

    @staticmethod
    def _merge_registry_entries(
        incoming: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        provider_configs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """整表替换解析：id 缺省则生成（m- + uuid）。

        2026-10-18 供应商中心化：条目经 ``provider_id`` 引用供应商，端点与密钥
        从供应商记录解析后展平进条目——**镜像逻辑与 AppConfig 取值路径因此零改动**。
        ``provider_id`` 指向不存在的供应商时该条目直接跳过（级联删除的兜底，
        正常路径由 :meth:`_validate_registry_entries` 先拦下并整单拒绝）。

        绝不做深合并，否则用户删除的参数会被「礼貌地」保留回来。
        """
        by_id = {str(e.get("id")): e for e in existing if e.get("id")}
        by_provider_id = {str(p.get("id")): p for p in provider_configs}
        merged: list[dict[str, Any]] = []
        for raw in incoming:
            entry_id = str(raw.get("id") or "").strip() or f"m-{uuid.uuid4().hex[:8]}"
            old = by_id.get(entry_id, {})
            record = by_provider_id.get(str(raw.get("provider_id") or "").strip())
            if record is None:
                continue
            provider = str(record.get("provider") or "").strip()
            model_id = str(raw.get("model_id") or "").strip()

            # api_mode：整体替换（None=沿用），并按 provider 的 supported_api_modes 收敛
            mode_in = raw.get("api_mode")
            mode_source = old.get("api_mode", "") if mode_in is None else mode_in
            api_mode = resolve_api_mode(provider, str(mode_source or ""))
            # 以下两者：空值 = 沿用旧值 / 不下发
            effort_in = raw.get("reasoning_effort")
            effort_source = old.get("reasoning_effort", "") if effort_in is None else effort_in
            effort = effort_source if isinstance(effort_source, str) else ""
            window_in = raw.get("max_context_length")
            window_source = old.get("max_context_length") if window_in is None else window_in
            window = window_source if isinstance(window_source, int) and window_source > 0 else None

            merged.append(
                {
                    "id": entry_id,
                    "provider_id": str(record.get("id", "")),
                    "provider": provider,
                    "base_url": str(record.get("base_url") or "").strip(),
                    "api_key": str(record.get("api_key") or ""),
                    "model_id": model_id,
                    "api_mode": api_mode,
                    "reasoning_effort": effort,
                    "max_context_length": window,
                }
            )
        return merged

    async def get_settings(self) -> dict[str, Any]:
        """F-604 读设置（T6-11）：有效配置视图（env 已并入）；api_key 恒脱敏，候选上限锁定只读。

        2026-10-18 供应商中心化重构：`provider_configs` 段是**用户自己配置的供应商**
        （端点 + 密钥，一个端点一份，密钥只脱敏回显）；`providers` 段仍是静态厂商目录
        （只读，下拉与档位的数据源）。两段同名易混，故前者带 `_configs` 后缀。
        复用本端点下发而非新增路径——契约仍 13 路径 / 16 操作。
        """
        cfg = self._cfg
        return {
            "models": self._registry_view(),
            "provider_configs": self._provider_configs_view(),
            "providers": providers_projection(),
            "model_service": {
                "provider": cfg.llm_provider,
                "base_url": cfg.llm_base_url,
                "api_key_masked": mask_secret(cfg.llm_api_key),
                "model_id": cfg.llm_model,
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

    @staticmethod
    def _validate_registry_entries(merged: list[dict[str, Any]]) -> list[str]:
        """写盘前校验注册表条目。返回问题描述列表（空 = 通过）。

        N-5 为什么要这一步：`_merge_registry_entries` 已做到「先算清再一次性写」，
        但它对**内容合法性**不设防——一个 `model_id` 为空的条目会被完整写入并可能成为
        激活项，用户得到的是「已保存」却根本调不通。宁可整单拒绝，也不要半成品。
        """
        problems: list[str] = []
        for index, entry in enumerate(merged):
            name = str(entry.get("model_id") or entry.get("id") or f"第 {index + 1} 项")
            if not str(entry.get("model_id", "")).strip():
                problems.append(f"{name}：缺少模型标识（model_id）")
            if not str(entry.get("base_url", "")).strip():
                problems.append(f"{name}：缺少服务地址（base_url）")
            api_key = entry.get("api_key", "")
            if api_key is not None and not isinstance(api_key, str):
                problems.append(f"{name}：api_key 必须是字符串")
        return problems

    async def update_settings(
        self, update: dict[str, Any], *, request_id: str = ""
    ) -> dict[str, Any]:
        """PUT /settings（T6-11 + 多模型注册表 F-604）：模型段写设置文件（0600）、流程段写表并应用。

        多模型注册表：``models`` 整表替换（api_key 空=沿用同 id 旧值）；``active_model_id`` 切换后
        把该条目**整体镜像**写入 model_service（provider/base_url/api_key/model_id）——AppConfig 与
        llm.py 取值路径零改动，密钥仍只落 0600 文件（MUST-19）。显式 model_service 段仍受支持。
        api_key 语义：空值/None = 保持不变；仅显式新值落盘（明文只进设置文件，不进库不进日志）。

        N-5 两阶段：先算清并校验全部条目 → 无误才单次原子写。任一条目不合法即整单拒绝，
        **不触碰存储**，避免留下「已保存但调不通」的半成品。
        N-6 部分失败可见：`skipped` 非空（如激活位指向不存在的条目）不报错但记事件与 context。
        """
        model_in: dict[str, Any] = dict(update.get("model_service") or {})
        process_in: dict[str, Any] = dict(update.get("process") or {})
        providers_in = update.get("provider_configs")
        models_in = update.get("models")
        active_in = update.get("active_model_id")
        skipped: list[str] = []
        registry = read_model_registry()
        # 供应商段为权威列表：未出现的记录删除，其下条目随 models 整表替换一并消失
        provider_configs = (
            self._merge_provider_configs([dict(p) for p in providers_in], registry["providers"])
            if providers_in is not None
            else registry["providers"]
        )

        # 注册表处理先于显式 model_service 段（后者若给同键可覆盖镜像值）
        if models_in is not None or active_in not in (None, "") or providers_in is not None:
            merged = (
                self._merge_registry_entries(
                    [dict(m) for m in models_in], registry["models"], provider_configs
                )
                if models_in is not None
                else registry["models"]
            )
            problems = self._validate_registry_entries(merged)
            if problems:
                raise ConfigurationError(
                    "模型注册表校验未通过，未写入任何改动：\n"
                    + "\n".join(f"  - {p}" for p in problems),
                    context={"problems": problems},
                )
            active_id = str(active_in).strip() if active_in not in (None, "") else ""
            if active_id and not any(str(e.get("id")) == active_id for e in merged):
                skipped.append("激活位指向不存在的条目，已保持原激活项")
                active_id = ""  # 激活位指向不存在条目：忽略该切换
            await asyncio.to_thread(
                write_model_registry,
                merged,
                active_id or None,
                provider_configs if providers_in is not None else None,
            )
            if skipped:
                emit(
                    "settings.updated",
                    skipped=len(skipped),
                    reasons=skipped,
                    request_id=request_id,
                )
            active_entry = next((e for e in merged if str(e.get("id")) == active_id), None)
            if active_entry is not None:
                mirror = {
                    "provider": str(active_entry.get("provider", "")),
                    "base_url": str(active_entry.get("base_url", "")),
                    "api_key": str(active_entry.get("api_key", "")),
                    "model_id": str(active_entry.get("model_id", "")),
                    # 该条目的参数覆盖（已按 provider 清洗）——让每模型参数真正生效
                    "llm_params": {},
                    # 该条目的 API 形态——让协议分流真正生效
                    "api_mode": str(active_entry.get("api_mode", "") or ""),
                    # 条目级上下文窗口：条目选中档位优先，其次回落到动态目录 / 静态表
                    # （dynamic 优先口径；仅告警不截断，F-918/MUST-25）
                    "max_context_length": self.effective_window(
                        str(active_entry.get("provider", "")),
                        str(active_entry.get("model_id", "")),
                        active_entry.get("max_context_length")
                        if isinstance(active_entry.get("max_context_length"), int)
                        else None,
                    )
                    or 0,
                }
                # reasoning_effort 并入 llm_params——这样 extra_body_params() 能读到它，
                # 无需 AppConfig 再加一个专用字段（KISS）。
                entry_effort = str(active_entry.get("reasoning_effort", "") or "")
                if entry_effort:
                    current = mirror.get("llm_params")
                    merged_params: dict[str, Any] = (
                        dict(current) if isinstance(current, dict) else {}
                    )
                    merged_params["reasoning_effort"] = entry_effort
                    mirror["llm_params"] = merged_params
                await asyncio.to_thread(write_model_settings, mirror)
                for src_key, value in mirror.items():
                    setattr(self._cfg, MODEL_KEY_MAP[src_key], value)

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
        settings = await self.get_settings()
        if skipped:
            # N-6：响应契约不变（不加字段），但把「跳过了什么」放进 context 供日志/测试检索
            settings["skipped"] = skipped
        return settings

    async def scan_project(self, project_root: str) -> dict[str, Any]:
        """F-101 只读统计（Web /project/scan 薄透传）：符号总数/文件数/类别分布。

        2026-10-20：异常转成带码的 DevPromptError（2001/2004）。此前裸抛 → 500 →
        前端只能猜测「路径不存在」，真实原因（工具失败）被掩盖。
        """
        if not await asyncio.to_thread(Path(project_root).is_dir):
            raise DevPromptError("项目路径不存在或不是目录", code=2001)
        try:
            table = await self._symbols_provider.get(project_root)
        except ProcessError as exc:
            raise DevPromptError("扫描失败：ctags 执行异常", code=2004) from exc
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

    def _observe_probe(self, probe: FactProbeOutput, request_id: str) -> None:
        """记录任务类型与提问形态合规。

        只发码与计数，**不含模型原文**（MUST-19）；不合规不阻断流程——
        用户 2026-10-20 裁定「原样展示，仅告警」。
        """
        emit(
            "followup.task_kind",
            task_kind=probe.task_kind,
            questions=len(probe.questions),
            request_id=request_id,
        )
        issues = lint_questions(probe.questions)
        if issues:
            emit_warning("followup.question_lint", issues=issues, request_id=request_id)

    async def _probe_and_route(
        self,
        session: FlowSession,
        *,
        request_id: str,
        progress: ProgressSink | None = None,
    ) -> FlowSnapshot:
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        probe = await self._decider.probe_facts(session.data["sentence"], facts)
        self._observe_probe(probe, request_id)
        if probe.ask_call_id:
            # AskUserQuestion 的 call_id：只落审计信息，不含原句（MUST-19）
            session.data["pending_tool_call"] = probe.ask_call_id
        session.data["probe_confidence"] = probe.overall_confidence
        unknowns = build_unknowns(probe, facts, clarifications=session.data.get("clarifications"))
        session.data["unknowns"] = [dataclasses.asdict(u) for u in unknowns]
        facts_complete = (
            bool(facts)
            and all(f.passed for f in facts)
            and probe.overall_confidence >= self._cfg.fact_probe_threshold
        )
        has_symbol = bool(session.data.get("target"))
        session.data["facts_complete"] = facts_complete
        session.data["level"] = resolve_level(has_symbol=has_symbol, facts_complete=facts_complete)
        await _notify(
            session,
            progress,
            level_text(str(session.data["level"]), float(probe.overall_confidence)),
        )
        if unknowns:
            await _notify(session, progress, clarification_text(len(unknowns)))
            await transition(session, FlowState.ASKING, self._sessions)
            await self._finish_turn(session)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session, progress=progress)

    async def _reprobe(self, session: FlowSession) -> FlowSnapshot:
        """F-204：答复后重新研判（取证结果不变，clarifications 已更新）。"""
        facts = [FactResult(**f) for f in session.data.get("facts", [])]
        probe = await self._decider.probe_facts(
            session.data["sentence"],
            facts,
            answered=dict(session.data.get("clarifications", {})),
        )
        self._observe_probe(probe, str(session.data.get("last_request_id", "")))
        if probe.ask_call_id:
            session.data["pending_tool_call"] = probe.ask_call_id
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
            await self._finish_turn(session)
            return self._snapshot(session, "guardrail")  # 停在 CONFIRMING 等裁决（6002 语义）
        if unknowns:
            await transition(session, FlowState.ASKING, self._sessions)
            await self._finish_turn(session)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session)

    async def _generate_and_finish(
        self, session: FlowSession, *, progress: ProgressSink | None = None
    ) -> FlowSnapshot:
        """GENERATING→(RANKING)→DONE：三套同调生成 + 加权推荐（5F，BREAKING）。

        状态机：≥2 套（B/C 档）经 RANKING 打分与判定后 DONE；仅 1 套（A 档
        escape/保守路径）按 MUST-28 跳过打分与推荐（不计算 d），直接 GENERATING→DONE。
        """
        await transition(session, FlowState.GENERATING, self._sessions)
        context_payload = await self._assemble_context(session)
        ctx = GenerationContext(
            sentence=session.data["sentence"],
            project_root=session.data["project_root"],
            level=session.data.get("level", "A"),
            facts_summary=session.data.get("facts_summary", _summarize_facts(session)),
            clarifications=session.data.get("clarifications", {}),
            conservative=bool(session.data.get("conservative", False)),
            history_block=context_payload.history_block,
            memory_block=context_payload.memory_block,
        )
        levels = plan_levels(
            ctx.level,
            max_versions=3 if self._should_offer_three(session) else 1,
            preferred=_preferred_level(session),
        )
        await _notify(session, progress, generation_text(levels))
        multi = await self._generator.generate_variants(ctx, levels)
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
            await _notify(session, progress, single_variant_text())
            await transition(session, FlowState.DONE, self._sessions)
            self._emit_completed(session, variants=len(multi.variants), marked=None)
            await self._finish_turn(session)
            return self._snapshot(session, "done")
        await transition(session, FlowState.RANKING, self._sessions)
        await _notify(session, progress, scoring_text())
        ranking = await self._rank_and_mark(session, multi.variants)
        session.data["ranking"] = dataclasses.asdict(ranking) if ranking is not None else None
        if ranking is not None:
            await _notify(
                session,
                progress,
                recommendation_text(ranking.marked, ranking.variant, ranking.gap, ranking.reason),
            )
        await transition(session, FlowState.DONE, self._sessions)
        self._emit_completed(
            session,
            variants=len(multi.variants),
            marked=ranking.marked if ranking is not None else None,
        )
        await self._finish_turn(session)
        return self._snapshot(session, "done")

    def _should_offer_three(self, session: FlowSession) -> bool:
        """三套只在「方向未定」时给（2026-10-20）：首轮 / 信息不完备 / 用户表达分歧。"""
        if int(session.data.get("turn_index", 0)) <= 0:
            return True
        if not bool(session.data.get("facts_complete", False)):
            return True
        if session.data.get("prev_facts_complete") is True and not session.data.get(
            "facts_complete", False
        ):
            return True  # 事实前提失效：上一轮完备、本轮不完备 → 重新展开
        sentence = str(session.data.get("sentence", ""))
        return any(word in sentence for word in _DIRECTION_CONFLICT_WORDS)

    async def _assemble_context(self, session: FlowSession) -> ContextPayload:
        """装配多轮上下文（纯函数在 domain/context）：历史摘要 + 偏好投影。

        L2 项目记忆在下一片接入；这里先传空笔记，保证分层与预算逻辑可独立回归。
        """
        summaries: list[TurnSummary] = []
        if self._turns is not None:
            for record in await self._turns.list_for_session(session.session_id):
                if record.state not in {"DONE", "ASKING"}:
                    continue
                summary = record.summary if isinstance(record.summary, dict) else {}
                summaries.append(
                    TurnSummary(
                        turn_id=record.turn_id,
                        turn_index=record.turn_index,
                        target=str(summary.get("target", "")),
                        conclusion=str(summary.get("conclusion", "")),
                        open_items=tuple(str(item) for item in summary.get("open", []) or []),
                        decision=str(summary.get("decision", "")),
                        rejected=tuple(str(item) for item in summary.get("rejected", []) or []),
                    )
                )
        target_data = session.data.get("target")
        current = TurnInput(
            sentence=str(session.data.get("sentence", "")),
            facts=tuple(
                f"{item.get('key')}={'通过' if item.get('passed') else '未通过'}"
                for item in session.data.get("facts", [])
                if isinstance(item, dict)
            ),
            clarifications=dict(session.data.get("clarifications", {})),
            target=str(target_data.get("name", "")) if isinstance(target_data, dict) else "",
        )
        notes: list[str] = []
        if self._notes is not None:
            target_path = str(target_data.get("path", "")) if isinstance(target_data, dict) else ""
            found = await self._notes.search(
                str(session.data.get("project_root", "")),
                target_key=normalize_key(current.target, target_path) if current.target else "",
            )
            notes = [note.render() for note in found]
        return build_context(
            summaries,
            current,
            notes=notes,
            budget=ContextBudget(total=self._cfg.max_state_tokens),
        )

    async def _begin_turn(self, session: FlowSession) -> None:
        """占位抢锁：同一 (session_id, turn_index) 只允许一个 turn 在跑（MUST-15）。

        在 LLM 调用之前 INSERT：并发或重复提交在数据库层被拒（6001），
        既不浪费一次生成，也不依赖前端防抖。
        """
        if self._turns is None:
            return
        index = int(session.data.get("turn_index", -1)) + 1
        turn_id = uuid.uuid4().hex
        try:
            await self._turns.append(
                TurnRecord(
                    turn_id=turn_id,
                    session_id=session.session_id,
                    turn_index=index,
                    state=FlowState.INIT.value,
                    input=str(session.data.get("sentence", "")),
                )
            )
        except TurnConflictError as exc:
            raise StateError(
                "该轮次已存在（重复提交或并发请求）",
                code=6001,
                context={"session_id": session.session_id, "turn_index": index},
            ) from exc
        except Exception:  # noqa: BLE001 - 存储故障不阻断主流程（与 feedback 降级一致）
            logger.warning("turn.begin_failed", exc_info=True)
            return
        session.data["turn_index"] = index
        session.data["current_turn_id"] = turn_id

    async def _finish_turn(self, session: FlowSession) -> None:
        """回填本轮产出（DONE / ASK 各一次）；失败只警告，不阻断流程。"""
        if self._turns is None:
            return
        turn_id = str(session.data.get("current_turn_id", ""))
        if not turn_id:
            return
        try:
            await self._turns.finish(
                turn_id,
                state=session.state,
                facts=[dict(item) for item in session.data.get("facts", [])],
                clarifications=dict(session.data.get("clarifications", {})),
                output=[dict(item) for item in session.data.get("variants", [])],
                summary=summary_from_turn(session.data),
                usage={"llm_tokens": int(session.data.get("cost_llm_tokens", 0))},
            )
        except Exception:  # noqa: BLE001 - 回填是旁路，读路径仍有 payload 兜底
            logger.warning("turn.finish_failed", exc_info=True)
        if self._notes is not None:
            try:
                await self._notes.record_from_session(
                    str(session.data.get("project_root", "")), session.data
                )
            except Exception:  # noqa: BLE001 - 记忆写入失败不阻断生成
                logger.warning("notes.record_failed", exc_info=True)

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
        request_id = session.data.get("last_request_id", "")
        try:
            context = str(session.data.get("facts_summary") or _summarize_facts(session))
            scores = await self._decider.score_prompts(
                context, [(v.level, v.body) for v in variants]
            )
            by_level = {s.variant: s for s in scores.scores}
            entries: list[tuple[VariantScore, float]] = []
            details: dict[str, tuple[float, float]] = {}
            for v in variants:
                score = by_level[v.level]
                fit = normalize_fit(score.score)
                # 2026-10-21：偏好记忆移除，总分 = 纯适配度（MUST-27 已同步修订）
                total = weighted_total(fit)
                entries.append((score, total))
                details[v.level] = (fit, total)
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
        top_fit, top_total = details[rec.variant]
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

    def _account_usage(self, session: FlowSession) -> None:
        """F-805：把本请求内已发生的外部模型调用用量并入会话（取用后累计器清零）。

        在快照组装时调用：此刻本请求的全部 LLM 调用均已完成，一次取用即全量入账；
        只读路径（resume）无新调用，累计器为零，不产生副作用。
        """
        llm_tokens = take_llm_tokens()
        if llm_tokens:
            session.data["cost_llm_tokens"] = (
                int(session.data.get("cost_llm_tokens", 0)) + llm_tokens
            )

    def _snapshot(self, session: FlowSession, status: SnapshotStatus) -> FlowSnapshot:
        self._account_usage(session)
        llm_tokens = int(session.data.get("cost_llm_tokens", 0))
        cost = CostBreakdown(
            llm_tokens=llm_tokens,
            total_tokens=llm_tokens,
            llm_source="actual" if llm_tokens > 0 else "no_call",
        )
        questions = [_unknown_from(raw) for raw in session.data.get("unknowns", [])]
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
            cost=cost,
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
            # M-3：会话不存在属**显式操作**失败（用户点了侧栏条目），必须 4xx 且文案可操作——
            # 不能降级为空快照，否则前端会误判为「会话无内容」而非「会话已失效」。
            raise StateError(
                "会话不存在或已过期，请从历史列表重新选择",
                code=6003,
                context={"session_id": session_id},
            )
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
    """MUST-14 缓存键影响因子：排序/推荐阈值配置的 json 序列化 sha256。

    阈值调整 → hash 变化 → 缓存失效，杜绝读到旧阈值下的排序结果；
    仅摘要入键，不落原句明文（MUST-14 禁缓存项）。
    """
    payload = json.dumps(
        {
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
    from devprompt_ai.harness.models_client import OpenAIModelsFetcher
    from devprompt_ai.memory.project_note_store import SQLiteProjectNoteStore
    from devprompt_ai.memory.session_store import SQLiteSessionStore
    from devprompt_ai.memory.startup_safety_check import run_startup_safety_check
    from devprompt_ai.memory.turn_store import SQLiteTurnStore

    # N-1 启动自愈：必须在任何 Manager 打开库之前跑，坏行隔离才有意义
    run_startup_safety_check(cfg.db_path)

    sessions = SQLiteSessionStore(cfg.db_path)
    await sessions.init_schema()
    return ForgeService(
        cfg=cfg,
        decider=create_decider(cfg),
        sessions=sessions,
        runner=LocalCommandRunner(),
        reader=LocalFileReader(),
        generator=LLMGenerator(cfg),
        symbols_provider=SymbolTableProvider(LocalCommandRunner()),
        catalog_fetcher=OpenAIModelsFetcher(),
        turns=SQLiteTurnStore(cfg.db_path),
        notes=SQLiteProjectNoteStore(cfg.db_path),
    )
