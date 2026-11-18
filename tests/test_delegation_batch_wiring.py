"""接线测试：委派波内批处理（只读并发受 explore 约束、写串行、结果按 id 落位）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.work_order import WorkOrder
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.service import ForgeService
from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols


def _service() -> ForgeService:
    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


def _session() -> FlowSession:
    return FlowSession(
        session_id="sess-abcdefgh1234",
        user_id="local",
        state="AGENTIC",
        data={"turn_id": "t1"},
    )


def _counter() -> tuple[Any, dict[str, int]]:
    state = {"active": 0, "peak": 0}

    async def execute(_order: WorkOrder) -> str:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.03)
        state["active"] -= 1
        return json.dumps({"summary": "ok", "evidence": []}, ensure_ascii=False)

    return execute, state


async def test_read_only_orders_run_concurrently() -> None:
    svc = _service()
    session = _session()
    orders = [
        WorkOrder(f"o{i}", "t1", "code_scout", f"查 {i}", scope_files=(f"src/f{i}.py",))
        for i in range(3)
    ]
    execute, state = _counter()

    await svc._run_delegation_waves(session, orders, execute=execute)  # noqa: SLF001

    assert state["peak"] == 2, "只读批并发受 explore_cap=2 约束"
    results = session.data["delegation"]["results"]
    assert set(results) == {"o0", "o1", "o2"}, "结果按工单 id 落位"
    assert all(item["status"] == "ok" for item in results.values())


async def test_write_orders_are_serialized() -> None:
    svc = _service()
    session = _session()
    orders = [
        WorkOrder(f"w{i}", "t1", "patcher", f"改 {i}", scope_files=(f"src/w{i}.py",))
        for i in range(2)
    ]
    execute, state = _counter()

    await svc._run_delegation_waves(session, orders, execute=execute)  # noqa: SLF001

    assert state["peak"] == 1, "写工单各自成批，串行作屏障"
    assert set(session.data["delegation"]["results"]) == {"w0", "w1"}
