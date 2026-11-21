"""P1 断点续跑回归：全量快照、reopen、副作用幂等、快照恢复循环。"""

from __future__ import annotations

import asyncio
from typing import Any

from devprompt_ai.memory.run_store import SQLiteRunStore


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_snapshot_roundtrip(tmp_path: Any) -> None:
    store = SQLiteRunStore(str(tmp_path / "runs.db"))

    async def _go() -> None:
        await store.init_schema()
        await store.create(run_id="r1", session_id="s1", turn_index=0, request_id="q1")
        snapshot = {"step": 5, "steps": [{"index": 1, "action": "probe"}], "session_data": {"a": 1}}
        await store.save_snapshot("r1", snapshot)
        loaded = await store.load_snapshot("r1")
        assert loaded == snapshot

    _run(_go())


def test_reopen_only_from_terminal(tmp_path: Any) -> None:
    store = SQLiteRunStore(str(tmp_path / "runs.db"))

    async def _go() -> None:
        await store.init_schema()
        await store.create(run_id="r1", session_id="s1", turn_index=0, request_id="q1")
        # running 不满足 reopen 条件（避免并发双执行）
        assert await store.reopen("r1") is False
        await store.finish("r1", "aborted", stop_reason="process-restart")
        assert await store.reopen("r1") is True
        record = await store.get("r1")
        assert record is not None and record.status == "running" and record.ended_at is None

    _run(_go())


def test_applied_ops_idempotent(tmp_path: Any) -> None:
    store = SQLiteRunStore(str(tmp_path / "runs.db"))

    async def _go() -> None:
        await store.init_schema()
        await store.create(run_id="r1", session_id="s1", turn_index=0, request_id="q1")
        await store.record_applied_op("r1", "ledger:0")
        await store.record_applied_op("r1", "ledger:0")  # 重复写不重复
        await store.record_applied_op("r1", "ledger:1")
        assert await store.load_applied_ops("r1") == ["ledger:0", "ledger:1"]

    _run(_go())


def test_delegation_skips_applied_orders() -> None:
    """续跑时已完成的工单不再重跑，且不覆盖快照里的旧结果。"""
    from devprompt_ai.config import AppConfig
    from devprompt_ai.domain.agent.work_order import WorkOrder
    from devprompt_ai.domain.models import FlowSession
    from devprompt_ai.harness.process import SymbolTableProvider
    from devprompt_ai.service import AppliedOps, ForgeService
    from devprompt_ai.state import FlowState
    from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols

    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    session = FlowSession(
        session_id="s1",
        user_id="local",
        state=FlowState.AGENTIC.value,
        data={"turn_index": 2, "facts": [], "project_root": "."},
    )
    order = WorkOrder(id="delegate-s1-0", parent_turn_id="t1", profile="code_scout", objective="x")
    applied = AppliedOps(keys={"delegation:2:delegate-s1-0"})

    async def _go() -> None:
        from devprompt_ai.service import _APPLIED_OPS

        token = _APPLIED_OPS.set(applied)
        try:
            result = await svc._run_one_order(session, order, None, execute=lambda o: None)  # noqa: SLF001
        finally:
            _APPLIED_OPS.reset(token)
        assert result is None

    _run(_go())


def test_resume_execution_restores_steps() -> None:
    """恢复时 steps 从快照还原，收敛判据不从头开始。"""
    from devprompt_ai.config import AppConfig
    from devprompt_ai.domain.agent.action import AgentAction
    from devprompt_ai.domain.models import FlowSession
    from devprompt_ai.harness.process import SymbolTableProvider
    from devprompt_ai.service import ForgeService
    from devprompt_ai.state import FlowState
    from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols

    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    session = FlowSession(
        session_id="s1",
        user_id="local",
        state=FlowState.AGENTIC.value,
        data={"sentence": "把提交按钮改成 primary", "project_root": ".", "facts": []},
    )
    captured: dict[str, Any] = {}

    async def _fake_loop(
        _session: Any, *, request_id: str, progress: Any = None, initial_steps: Any = None
    ) -> Any:
        captured["steps"] = list(initial_steps or [])
        return None

    svc.run_agent_loop = _fake_loop  # type: ignore[method-assign]

    async def _go() -> None:
        await svc._sessions.create(session)  # noqa: SLF001
        snapshot = {
            "session_data": {"sentence": "把提交按钮改成 primary", "project_root": "."},
            "steps": [
                {
                    "index": 0,
                    "action": "probe",
                    "outcome": "ok",
                    "duration_ms": 3,
                    "facts_passed": 2,
                },
                {
                    "index": 1,
                    "action": "generate",
                    "outcome": "ok",
                    "duration_ms": 5,
                    "facts_passed": 2,
                },
            ],
        }
        await svc.resume_execution("local", "s1", request_id="r1", snapshot=snapshot)
        steps = captured["steps"]
        assert [step.action for step in steps] == [AgentAction.PROBE, AgentAction.GENERATE]
        assert steps[0].facts_passed == 2

    _run(_go())
