"""DetectorHook（E9–E10）测试：post_tool 的自检与死路建议。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome
from devprompt_ai.domain.hooks.builtin import DetectorHook
from devprompt_ai.domain.hooks.types import HookContext


def _step(index: int, action: AgentAction, *, outcome: StepOutcome = StepOutcome.OK) -> AgentStep:
    return AgentStep(index=index, action=action, outcome=outcome, duration_ms=1, facts_passed=0)


def _ctx(steps: list[AgentStep]) -> HookContext:
    return HookContext(phase="post_tool", session_state="AGENTIC", data={"steps": steps})


def test_read_only_streak_suggests_self_verify() -> None:
    steps = [_step(i, AgentAction.PROBE) for i in range(5)]

    result = DetectorHook().run(_ctx(steps))

    assert result.verdict == "correct"
    assert "独立验证" in (result.reason or "")


def test_generate_step_breaks_read_only_streak() -> None:
    steps = [_step(i, AgentAction.PROBE) for i in range(4)]
    steps.append(_step(4, AgentAction.GENERATE))

    result = DetectorHook().run(_ctx(steps))

    assert result.verdict == "allow"


def test_repeated_failed_action_suggests_new_route() -> None:
    steps = [_step(i, AgentAction.RETRIEVE, outcome=StepOutcome.FAILED) for i in range(3)]

    result = DetectorHook().run(_ctx(steps))

    assert result.verdict == "correct"
    assert "换一种做法" in (result.reason or "")


def test_empty_steps_are_allow() -> None:
    assert DetectorHook().run(_ctx([])).verdict == "allow"
