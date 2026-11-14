"""可观测性四模块 E2E 的公共假件与断言工具（不依赖真实 LLM / 外网）。"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.decision.port import (
    FactJudgment,
    FactProbeOutput,
    NextActionOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.generate.ports import VariantDraft
from devprompt_ai.domain.models import FactResult, FlowSession, SessionSummary, Symbol
from devprompt_ai.domain.obs.contract.trace import TraceEvent
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.harness.obs.traced_ports import (
    TracedDecider,
    TracedGenerator,
    TracedReader,
    TracedRunner,
    TracedSymbolProvider,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.memory_stores import MemoryTurnStore
from devprompt_ai.service import ForgeService

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_PROJECT = REPO_ROOT / "eval" / "recall" / "mock-react-admin"

#: ctags --output-format=json 的固定行走势（与真实 ctags 字段一致）
CTAGS_JSON = "\n".join(
    [
        '{"_type":"tag","name":"SubmitButton","path":"src/components.tsx","line":3,"kind":"function"}',
        '{"_type":"tag","name":"SubmitButtonGroup","path":"src/components.tsx","line":11,"kind":"function"}',
        '{"_type":"tag","name":"SubmitForm","path":"src/components.tsx","line":25,"kind":"function"}',
    ]
)


class FakeStore:
    """内存 SessionStore（E2E 不触碰真实用户库）。"""

    def __init__(self) -> None:
        self.items: dict[str, FlowSession] = {}

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        return []

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        return 0


class FakeRunner:
    """ctags 返回固定符号表；rg 按查询词命中固定证据。"""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str]] = [
            ("SubmitButton", "src/components.tsx:3:export function SubmitButton()"),
            ("--color-primary-500", "src/styles/tokens.css:2:  --color-primary-500: #3b82f6"),
            ("data-testid", "src/components.tsx:5:  data-testid='submit-btn'"),
            (":hover", "src/components.tsx:0:  // no hover"),
        ]

    async def run(self, args: list[str], **kw: Any) -> str:
        if args and args[0] == "ctags":
            return CTAGS_JSON
        for needle, out in self.routes:
            if any(needle in arg for arg in args):
                return out
        return ""


class FakeReader:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or {
            "src/components.tsx",
            "src/components.test.tsx",
            "src/styles/tokens.css",
        }

    async def read(self, path: str) -> str:
        return (
            "import { useState } from 'react'\n"
            "export function SubmitButton() { "
            "return <button data-testid='submit-btn'>提交</button> }\n"
            "/* --color-primary-500 */\n"
        )

    async def exists(self, path: str) -> bool:
        return path in self.existing or path.endswith("components.tsx")


class FakeGenerator:
    async def generate_single(  # type: ignore[no-untyped-def]
        self, ctx: Any, locale: str = "zh-CN", *, fallback: bool = False
    ) -> VariantDraft:
        return VariantDraft(
            title="把 SubmitButton 改成品牌蓝",
            body="使用 --color-primary-500",
            changes=["src/components.tsx"],
            fallback=fallback,
        )

    async def answer(self, ctx: Any, locale: str = "zh-CN") -> str:
        return "这是纯回答"


class ScriptedDecider:
    """按脚本吐动作的决策层替身。"""

    def __init__(
        self,
        actions: Sequence[AgentAction] | None = None,
        *,
        probe_output: FactProbeOutput | None = None,
    ) -> None:
        self.actions = list(
            actions
            or [
                AgentAction.RETRIEVE,
                AgentAction.PROBE,
                AgentAction.GENERATE,
                AgentAction.DELIVER,
            ]
        )
        self.probe_output = probe_output
        self.calls = 0

    async def next_action(
        self,
        *,
        sentence: str,
        facts: Sequence[FactResult],
        steps: Sequence[Any],
        variant_count: int,
        clarifications: Any,
        correction: str = "",
        inherited_variant_count: int = 0,
    ) -> NextActionOutput:
        action = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        return NextActionOutput(
            action=action.value,
            reason=f"选 {action.value}",
            confidence=0.9,
            confidence_source="measured",
        )

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Any = None,
    ) -> FactProbeOutput:
        if self.probe_output is not None:
            return self.probe_output
        return FactProbeOutput(
            judgments=[FactJudgment(key=f.key, passed=f.passed, confidence=0.9) for f in facts],
            overall_confidence=0.9,
        )

    async def rank_components(self, sentence: str, candidates: list[Any]) -> RankComponentsOutput:
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        return ScorePromptsOutput(
            scores=[
                VariantScore(variant=key, score=3, confidence=0.9)  # type: ignore[arg-type]
                for key, _ in variants
            ]
        )


def symbols() -> list[Symbol]:
    return [
        Symbol(name="SubmitButton", path="src/components.tsx", line=3, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/components.tsx", line=11, kind="function"),
        Symbol(name="SubmitForm", path="src/components.tsx", line=25, kind="function"),
    ]


@dataclass
class FakeStack:
    """一套可直接跑 ForgeService 的 fake 栈（Trace 走真实采集器与 SQLite）。"""

    service: ForgeService
    collector: TraceCollectorImpl
    store: SQLiteTraceStore
    sessions: FakeStore = field(default_factory=FakeStore)


def build_stack(
    cfg: AppConfig,
    collector: TraceCollectorImpl,
    *,
    decider: Any | None = None,
    generator: Any | None = None,
    record_symbols: bool = False,
) -> FakeStack:
    """构造 Traced 包装的完整服务；``record_symbols=True`` 时不使用 override（可回放）。"""
    runner = FakeRunner()
    reader = FakeReader()
    sessions = FakeStore()
    provider: Any = SymbolTableProvider(runner, ttl_seconds=0.0)
    if record_symbols:
        provider = TracedSymbolProvider(provider, collector)
    service = ForgeService(
        cfg=cfg,
        decider=TracedDecider(decider or ScriptedDecider(), collector),
        sessions=sessions,
        runner=TracedRunner(runner, collector),
        reader=TracedReader(reader, collector),
        generator=TracedGenerator(generator or FakeGenerator(), collector),
        symbols_provider=provider,
        symbols_override=None if record_symbols else symbols(),
        turns=MemoryTurnStore(),
        trace=collector,
    )
    return FakeStack(
        service=service,
        collector=collector,
        store=SQLiteTraceStore(cfg.db_path),
        sessions=sessions,
    )


def make_event(
    seq: int,
    kind: str,
    *,
    trace_id: str = "s1:0:req",
    session_id: str = "s1",
    turn_index: int = 0,
    run_id: str = "req-1",
    status: str = "ok",
    duration_ms: int = 10,
    name: str = "",
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    parent_id: str = "",
) -> TraceEvent:
    return TraceEvent(
        event_id=f"e-{trace_id}-{seq}",
        trace_id=trace_id,
        session_id=session_id,
        turn_id=f"turn-{turn_index}",
        turn_index=turn_index,
        run_id=run_id,
        seq=seq,
        parent_id=parent_id,
        kind=kind,
        name=name or kind,
        status=status,
        started_at=f"2026-11-13T10:{seq // 60:02d}:{seq % 60:02d}.000Z",
        ended_at=f"2026-11-13T10:{seq // 60:02d}:{seq % 60:02d}.500Z",
        duration_ms=duration_ms,
        input=input or {},
        output=output or {},
        error={} if status == "ok" else {"type": "E", "message": "failed"},
        attributes=attributes or {"model_id": "deepseek-flash", "tokens": 100},
        schema_version=1,
    )


def seed_trace(
    store: Any,
    *,
    trace_id: str,
    session_id: str,
    turn_index: int,
    run_id: str,
    count: int = 30,
    kinds: Sequence[str] | None = None,
) -> list[TraceEvent]:
    """写入一条完整 Trace：turn.start → 若干节点 → turn.end（seq 从 1 连续）。"""
    kinds = list(kinds or ["decision.response", "tool.result", "llm.response", "action.end"])
    events: list[TraceEvent] = [
        make_event(
            1,
            "turn.start",
            trace_id=trace_id,
            session_id=session_id,
            turn_index=turn_index,
            run_id=run_id,
            input={
                "sentence": "把 SubmitButton 的主色改成 --color-primary-500",
                "project_root": "eval/recall/mock-react-admin",
                "session_data": {"sentence": "x", "project_root": "eval/recall/mock-react-admin"},
            },
            attributes={"input_hash": f"hash-{turn_index}", "run_id": run_id},
        )
    ]
    for index in range(2, count):
        events.append(
            make_event(
                index,
                kinds[(index - 2) % len(kinds)],
                trace_id=trace_id,
                session_id=session_id,
                turn_index=turn_index,
                run_id=run_id,
            )
        )
    events.append(
        make_event(
            count,
            "turn.end",
            trace_id=trace_id,
            session_id=session_id,
            turn_index=turn_index,
            run_id=run_id,
            output={"state": "DONE", "snapshot": {"status": "done", "state": "DONE"}},
        )
    )
    return events


def percentile(values: Sequence[float], pct: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def assert_seq_contiguous(events: Sequence[TraceEvent], trace_id: str) -> None:
    seqs = [event.seq for event in events if event.trace_id == trace_id]
    assert seqs == list(range(1, len(seqs) + 1)), f"seq 不连续：{trace_id} {seqs[:5]}..."


async def wait_until(predicate: Any, *, timeout: float = 5.0, interval: float = 0.02) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        import asyncio

        await asyncio.sleep(interval)
    return await predicate()


async def create_container(sessions: Any, *, user_id: str = "local") -> FlowSession:
    """预建一个已完成容器（模拟前端新建会话后提交 /runs 的既有会话）。"""
    import uuid

    session = FlowSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        state="DONE",
        data={},
    )
    await sessions.create(session)
    return session
