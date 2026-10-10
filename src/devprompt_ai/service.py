"""F-001 统一业务入口（双形态唯一，MUST-07/10）。业务判定只在此层与 domain/。"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.followup import GuardrailState, UnknownItem, build_unknowns
from devprompt_ai.domain.decision.port import DecisionPort
from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.generate.ports import GeneratePort, GenerationContext, VariantDraft
from devprompt_ai.domain.generate.variants import resolve_level
from devprompt_ai.domain.models import FactResult, FlowSession, SessionStore, Symbol
from devprompt_ai.domain.retrieval.candidates import build_candidates
from devprompt_ai.domain.retrieval.facts import verify_facts
from devprompt_ai.domain.retrieval.locate import locate_symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader
from devprompt_ai.harness.llm import LLMGenerator, last_usage
from devprompt_ai.harness.process import LocalCommandRunner, LocalFileReader, SymbolTableProvider
from devprompt_ai.state import FlowState, load_or_create, transition

logger = logging.getLogger("devprompt.flow")

Preference = dict[str, float]
SnapshotStatus = Literal["ask", "done", "guardrail"]
_INITIAL_PREFERENCE: Preference = {
    "detail_level": 0.5,
    "include_diff": 0.5,
    "specify_tests": 0.5,
    "max_files_norm": 0.5,
}


@dataclass(slots=True)
class FlowSnapshot:
    """表现层快照：CLI/Web 只渲染它（MUST-10）。"""

    session_id: str
    status: SnapshotStatus
    state: str
    questions: list[UnknownItem] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    variant: VariantDraft | None = None
    message: str = ""


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
        symbols_override: list[Symbol] | None = None,
    ) -> None:
        self._cfg = cfg
        self._decider = decider
        self._sessions = sessions
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
        session.data = {
            "sentence": sentence,
            "project_root": project_root,
            "last_request_id": request_id,
            "clarifications": {},
            "rounds": 0,
            "cost_tokens": 0,
        }
        await transition(session, FlowState.RETRIEVING, self._sessions)

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

        top = result.candidates[0]
        symbol = Symbol(name=top.name, path=top.path, line=top.line, kind="function")
        location = await locate_symbol(symbol, self._runner, self._reader, root=project_root)
        facts = await verify_facts(
            location, sentence, self._runner, self._reader, root=project_root
        )
        session.data["facts"] = [
            {"key": f.key, "passed": f.passed, "evidence": f.evidence} for f in facts
        ]
        session.data["target"] = {"name": top.name, "path": top.path}
        await transition(session, FlowState.PROBING, self._sessions)
        return await self._probe_and_route(session, request_id=request_id)

    async def ask_followup(
        self, user_id: str, session_id: str, answers: dict[str, str], *, request_id: str
    ) -> FlowSnapshot:
        """F-204：批量答复 → 重新研判 → ask/guardrail/done。"""
        session = await self._require(user_id, session_id, {FlowState.ASKING, FlowState.CONFIRMING})
        session.data.setdefault("clarifications", {}).update(answers)
        session.data["last_request_id"] = request_id
        session.data["rounds"] = int(session.data.get("rounds", 0)) + 1
        await transition(session, FlowState.CONFIRMING, self._sessions)
        return await self._reprobe(session)

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
        logger.info(
            "followup.escaped",
            extra={"rounds": session.data.get("rounds", 0), "request_id": request_id},
        )
        session.data["level"] = "A"
        session.data["conservative"] = True
        return await self._generate_and_finish(session)

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FlowSnapshot:
        """MUST-26 ③：软护栏裁决——继续追问（清零）或直接生成。"""
        session = await self._require(user_id, session_id, {FlowState.CONFIRMING})
        if proceed:
            session.data["rounds"] = 0
            await transition(session, FlowState.ASKING, self._sessions)
            return self._snapshot(session, "ask")
        session.data["level"] = "A"
        session.data["conservative"] = True
        return await self._generate_and_finish(session)

    async def get_preference(self, user_id: str) -> Preference:
        """L3 偏好（阶段五接 SQLite L3；当前返回初始向量）。"""
        return dict(_INITIAL_PREFERENCE)

    async def feedback(
        self, user_id: str, session_id: str, action: str, *, request_id: str
    ) -> None:
        """F-603 采纳反馈：阶段五写 L3；当前记录日志。"""
        logger.info(
            "feedback.received",
            extra={
                "action": action,
                "user_id": user_id,
                "session_id": session_id,
                "request_id": request_id,
            },
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
            logger.info(
                "followup.guardrail",
                extra={
                    "rounds": guard.rounds,
                    "cost_tokens": guard.cost_tokens,
                    "request_id": session.data.get("last_request_id", ""),
                },
            )
            return self._snapshot(session, "guardrail")  # 停在 CONFIRMING 等裁决（6002 语义）
        if unknowns:
            await transition(session, FlowState.ASKING, self._sessions)
            return self._snapshot(session, "ask")
        return await self._generate_and_finish(session)

    async def _generate_and_finish(self, session: FlowSession) -> FlowSnapshot:
        await transition(session, FlowState.GENERATING, self._sessions)
        ctx = GenerationContext(
            sentence=session.data["sentence"],
            project_root=session.data["project_root"],
            level=session.data.get("level", "A"),
            facts_summary=session.data.get("facts_summary", _summarize_facts(session)),
            clarifications=session.data.get("clarifications", {}),
            conservative=bool(session.data.get("conservative", False)),
        )
        draft = await self._generator.generate_single(ctx)
        usage = last_usage()
        if usage:
            session.data["cost_tokens"] = (
                int(session.data.get("cost_tokens", 0)) + usage["total_tokens"]
            )
        session.data["variant"] = {
            "title": draft.title,
            "body": draft.body,
            "changes": draft.changes,
            "level": draft.level,
        }
        await transition(session, FlowState.DONE, self._sessions)  # RANKING 阶段五接入
        return self._snapshot(session, "done")

    def _snapshot(self, session: FlowSession, status: SnapshotStatus) -> FlowSnapshot:
        questions = [UnknownItem(**u) for u in session.data.get("unknowns", [])]
        return FlowSnapshot(
            session_id=session.session_id,
            status=status,
            state=session.state,
            questions=questions,
            cleared=sorted(session.data.get("clarifications", {}).keys()),
            variant=VariantDraft(**session.data["variant"]) if "variant" in session.data else None,
        )

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


async def build_default(cfg: AppConfig) -> ForgeService:
    """默认组装（CLI/开发态；Web 复用同一函数，MUST-10）。"""
    from devprompt_ai.decision.fallback import create_decider
    from devprompt_ai.memory.session_store import SQLiteSessionStore

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
    )
