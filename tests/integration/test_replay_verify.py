"""Replay verify 端到端：用采到的 Trace 确定性重跑并自比对（不调真实 LLM/工具）。"""

from __future__ import annotations

import asyncio
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.harness.obs.traced_ports import (
    TracedDecider,
    TracedGenerator,
    TracedReader,
    TracedRunner,
    TracedSymbolProvider,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.replay_service import ReplayService
from devprompt_ai.service import ForgeService
from test_agent_loop import CtagsRunner, ScriptedDecider, _action
from test_service import FakeGenerator, FakeReader, FakeRunner, FakeStore

_EXISTING_FILES = {"src/ui/button.tsx", "src/ui/button.test.tsx"}


async def test_replay_verify_matches_recorded_trace(tmp_path: Any) -> None:
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
        reader=TracedReader(FakeReader(_EXISTING_FILES), collector),
        generator=TracedGenerator(FakeGenerator(), collector),
        symbols_provider=TracedSymbolProvider(
            SymbolTableProvider(CtagsRunner(), ttl_seconds=0.0), collector
        ),
        trace=collector,
    )
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="req-1")
    await collector.flush_all()

    traces = await store.list_traces(snap.session_id)
    assert len(traces) == 1, "一轮应产出一条 Trace"

    service = ReplayService(
        store,
        SQLiteReplayStore(db),
        AppConfig(_env_file=None),  # type: ignore[call-arg]
    )
    await service.startup()
    record = await service.create(mode="verify", left_trace_id=traces[0].trace_id)

    latest = record
    nodes: list[Any] = []
    for _ in range(200):
        row, nodes = await service.get(record.run_id)
        if row is not None:
            latest = row
            if latest.status != "running":
                break
        await asyncio.sleep(0.02)

    bad = [node.diff for node in nodes if not node.match][:3]
    assert latest.status == "matched", bad or latest.error
    assert nodes, "回放应产出逐节点比对结果"
