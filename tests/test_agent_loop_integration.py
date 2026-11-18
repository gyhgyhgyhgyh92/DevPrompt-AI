"""Agentic loop 集成测试：完整 run_agent_loop 走通三条终止路径。

覆盖打转（wedged-loop）、步数预算耗尽（max-turns）、外环熔断（convergence-abort）——
不是测判定函数，而是测「判定 → 终止原因 → 会话终态」在真实循环里的接线。
"""

from __future__ import annotations

from typing import Any, Literal, cast

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.stop_reason import StopReason
from devprompt_ai.domain.decision.port import NextActionOutput
from devprompt_ai.domain.hooks.pipeline import HookOutcome, HookPipeline
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.service import ForgeService
from devprompt_ai.state import FlowState
from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols

ActionLiteral = Literal[
    "retrieve",
    "probe",
    "ask",
    "generate",
    "rank",
    "deliver",
    "abort",
    "reply",
    "delegate",
]


class PlannerDecider(FakeDecider):
    """按脚本返回动作的决策替身：实现 ActionPlanner，loop 走真实调度路径。"""

    def __init__(self, actions: list[ActionLiteral]) -> None:
        super().__init__([0.9] * 7)
        self._actions = actions
        self.calls = 0

    async def next_action(self, **_kwargs: Any) -> NextActionOutput:
        action = self._actions[min(self.calls, len(self._actions) - 1)]
        self.calls += 1
        return NextActionOutput(action=action, reason="脚本动作", confidence=0.9)


def _service(decider: Any) -> ForgeService:
    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=decider,
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


async def _session(svc: ForgeService) -> FlowSession:
    session = FlowSession(
        session_id="s1",
        user_id="local",
        state=FlowState.INIT.value,
        data={
            "sentence": "把提交按钮改成 primary",
            "project_root": ".",
            "facts": [],
            "turn_index": 0,
        },
    )
    await svc._sessions.create(session)  # noqa: SLF001
    return session


async def test_loop_stops_on_repeated_action_without_new_facts() -> None:
    """连续同动作且事实数无增长 → 打转熔断（wedged-loop），会话落到 aborted。"""
    svc = _service(PlannerDecider(["probe"]))
    session = await _session(svc)

    snapshot = await svc.run_agent_loop(session, request_id="r1")  # noqa: SLF001

    assert snapshot is not None and snapshot.status == "aborted"
    assert session.data["stop_reason"] == StopReason.WEDGED_LOOP.value


async def test_loop_stops_when_step_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """步数预算耗尽 → max-turns；用小预算验证接线，不依赖 24 这个常量。"""
    from devprompt_ai.domain.agent.action import AgentBudget as RealBudget

    class SmallBudget(RealBudget):
        def __init__(self) -> None:
            super().__init__(max_steps=3)

    monkeypatch.setattr("devprompt_ai.service.AgentBudget", SmallBudget)
    # 轮换非终止动作（reply/deliver 是终止动作，会直接收尾）：既避开打转判定，又走满预算
    svc = _service(PlannerDecider(["probe", "generate", "probe", "generate", "probe"]))
    session = await _session(svc)

    snapshot = await svc.run_agent_loop(session, request_id="r2")  # noqa: SLF001

    assert snapshot is not None and snapshot.status == "aborted"
    assert session.data["stop_reason"] == StopReason.MAX_TURNS.value


async def test_loop_halts_on_hook_verdict() -> None:
    """外环 hook 判 halt → 收敛熔断（convergence-abort）。"""

    class HaltingHooks:
        async def run_phase(self, _phase: str, _ctx: Any) -> HookOutcome:
            return HookOutcome(verdict="halt", reason="测试熔断")

    svc = _service(PlannerDecider(["probe", "reply", "probe", "reply"]))
    svc._hooks = cast(HookPipeline, HaltingHooks())  # noqa: SLF001
    session = await _session(svc)

    snapshot = await svc.run_agent_loop(session, request_id="r3")  # noqa: SLF001

    assert snapshot is not None and snapshot.status == "aborted"
    assert session.data["stop_reason"] == StopReason.CONVERGENCE_ABORT.value
