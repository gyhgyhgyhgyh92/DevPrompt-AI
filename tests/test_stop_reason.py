"""终止原因测试：分类、终态与快照映射。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome
from devprompt_ai.domain.agent.stop_reason import (
    StopReason,
    StopRecord,
    snapshot_stop_reason,
)
from devprompt_ai.service import ForgeService


def test_guard_and_voluntary_are_disjoint() -> None:
    guard = StopRecord(StopReason.CONVERGENCE_ABORT)
    voluntary = StopRecord(StopReason.NATURAL_FINISH)

    assert guard.is_guard is True
    assert guard.is_voluntary is False
    assert voluntary.is_voluntary is True
    assert voluntary.is_guard is False


def test_checkpoint_is_not_terminal() -> None:
    assert StopRecord(StopReason.CHECKPOINT).is_terminal is False
    assert StopRecord(StopReason.MAX_TURNS).is_terminal is True


def test_snapshot_mapping() -> None:
    assert snapshot_stop_reason("done", "DONE") is StopReason.NATURAL_FINISH
    assert snapshot_stop_reason("ask", "ASKING") is StopReason.END_TURN
    assert snapshot_stop_reason("aborted", "ABORTED") is StopReason.USER_INTERRUPT
    assert snapshot_stop_reason("guardrail", "CONFIRMING") is StopReason.END_TURN


def test_all_reasons_have_unique_values() -> None:
    values = [reason.value for reason in StopReason]

    assert len(values) == len(set(values)) == 12


def _step(index: int, action: AgentAction, facts: int) -> AgentStep:
    return AgentStep(
        index=index,
        action=action,
        outcome=StepOutcome.OK,
        duration_ms=1,
        facts_passed=facts,
    )


def test_wedged_after_four_identical_actions_without_progress() -> None:
    steps = [_step(i, AgentAction.RETRIEVE, 3) for i in range(4)]

    assert ForgeService._is_wedged(steps) is True


def test_not_wedged_when_facts_grow() -> None:
    steps = [_step(i, AgentAction.RETRIEVE, i) for i in range(4)]

    assert ForgeService._is_wedged(steps) is False


def test_not_wedged_when_actions_vary() -> None:
    steps = [
        _step(0, AgentAction.RETRIEVE, 1),
        _step(1, AgentAction.PROBE, 1),
        _step(2, AgentAction.GENERATE, 1),
        _step(3, AgentAction.DELIVER, 1),
    ]

    assert ForgeService._is_wedged(steps) is False


def test_not_wedged_when_steps_are_too_few() -> None:
    assert ForgeService._is_wedged([_step(0, AgentAction.RETRIEVE, 0)]) is False
