"""A2/A6/A7 测试：六道闸、可中断等待、请求级预算断言。"""

from __future__ import annotations

import asyncio

import pytest

from devprompt_ai.domain.agent.finish_gates import (
    FinishGate,
    GateInput,
    evaluate_finish,
)
from devprompt_ai.domain.context.budget import (
    RequestBudgetError,
    ensure_request_fits,
    request_budget,
)
from devprompt_ai.harness.abort import reject_on_abort


def test_all_gates_pass() -> None:
    decision = evaluate_finish(GateInput(has_text=True))

    assert decision.allowed is True
    assert decision.blocked_by is None


def test_each_gate_blocks_in_order() -> None:
    thinking = evaluate_finish(GateInput(has_text=True, text_looks_like_thinking=True))
    steer = evaluate_finish(GateInput(has_text=True, pending_steer="改用 B 方案"))
    goal = evaluate_finish(GateInput(has_text=True, pending_goal="还差测试"))
    empty = evaluate_finish(GateInput(has_text=False))
    intent = evaluate_finish(GateInput(has_text=True, states_future_action=True))
    obligation = evaluate_finish(GateInput(has_text=True, pending_obligation="未验证"))

    assert thinking.blocked_by is FinishGate.THINKING_RETRY
    assert steer.blocked_by is FinishGate.STEER
    assert goal.blocked_by is FinishGate.GOAL
    assert empty.blocked_by is FinishGate.NO_ANSWER
    assert intent.blocked_by is FinishGate.ACTION_INTENT
    assert obligation.blocked_by is FinishGate.OBLIGATION
    assert all(item.allowed is False for item in (thinking, steer, goal, empty, intent, obligation))


def test_thinking_passes_when_retry_budget_exhausted() -> None:
    decision = evaluate_finish(
        GateInput(
            has_text=True,
            text_looks_like_thinking=True,
            retry_budget_left=False,
        )
    )

    assert decision.allowed is True, "重试预算用完时不能再拦，否则死循环"


def test_steer_beats_goal() -> None:
    decision = evaluate_finish(
        GateInput(has_text=True, pending_steer="先停", pending_goal="还差测试")
    )

    assert decision.blocked_by is FinishGate.STEER


async def test_abort_guard_passes_result_through() -> None:
    async def work() -> str:
        return "ok"

    assert await reject_on_abort(work(), None, label="test") == "ok"


async def test_abort_guard_stops_when_signal_already_set() -> None:
    signal = asyncio.Event()
    signal.set()

    with pytest.raises(asyncio.CancelledError):
        await reject_on_abort(asyncio.sleep(1), signal, label="test")


async def test_abort_guard_stops_while_waiting() -> None:
    signal = asyncio.Event()

    async def slow() -> str:
        await asyncio.sleep(5)
        return "late"

    async def trigger() -> None:
        await asyncio.sleep(0.01)
        signal.set()

    trigger_task = asyncio.create_task(trigger())
    with pytest.raises(asyncio.CancelledError):
        await reject_on_abort(slow(), signal, label="test")
    await trigger_task


def test_request_budget_assertion() -> None:
    budget = request_budget(window=100_000, max_output=10_000)

    ensure_request_fits(1_000, budget)
    with pytest.raises(RequestBudgetError):
        ensure_request_fits(budget.input_budget + 1, budget)
