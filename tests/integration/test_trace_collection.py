"""Trace 采集集成：直接调用 ForgeService 也能产生完整事件链。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.obs.contract.trace import TraceKind
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.harness.obs.traced_ports import (
    TracedDecider,
    TracedGenerator,
    TracedReader,
    TracedRunner,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.service import ForgeService
from test_agent_loop import ScriptedDecider, _action
from test_service import FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols


async def test_direct_optimize_records_full_trace(tmp_path: Any) -> None:
    db = str(tmp_path / "obs.db")
    store = SQLiteTraceStore(db)
    await store.init_schema()
    collector = TraceCollectorImpl(store, buffer_size=100)
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=TracedDecider(decider, collector),
        sessions=FakeStore(),
        runner=TracedRunner(FakeRunner(), collector),
        reader=TracedReader(FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}), collector),
        generator=TracedGenerator(FakeGenerator(), collector),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
        trace=collector,
    )
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="req-1")
    await collector.flush_all()

    traces = await store.list_traces(snap.session_id)
    assert len(traces) == 1
    events = await store.list_trace_events(traces[0].trace_id)
    kinds = {event.kind for event in events}
    assert TraceKind.TURN_START.value in kinds
    assert TraceKind.TURN_END.value in kinds
    assert TraceKind.ACTION_START.value in kinds
    assert TraceKind.ACTION_END.value in kinds
    assert TraceKind.DECISION.value in kinds
    assert TraceKind.DECISION_RESULT.value in kinds
    assert TraceKind.FILE.value in kinds
    assert TraceKind.TOOL.value in kinds
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    start = next(event for event in events if event.kind == TraceKind.TURN_START.value)
    assert start.input["sentence"] == "把提交按钮改成 primary-500"
    assert "session_data" in start.input
