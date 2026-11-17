"""重试测试：退避上限、共享预算、可中断等待。"""

from __future__ import annotations

import asyncio

from devprompt_ai.harness.retry import (
    RetryBudget,
    RetryPolicy,
    abortable_sleep,
    next_delay,
)


def test_next_delay_is_exponential_and_capped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=8.0, jitter_ratio=0.0)

    assert next_delay(1, policy) == 1.0
    assert next_delay(2, policy) == 2.0
    assert next_delay(4, policy) == 8.0
    assert next_delay(9, policy) == 8.0, "封顶后不再增长"


def test_next_delay_jitter_within_ratio() -> None:
    policy = RetryPolicy(base_delay_s=10.0, jitter_ratio=0.5)

    delay = next_delay(1, policy)

    assert 10.0 <= delay <= 15.0


def test_retry_budget_blocks_after_capacity() -> None:
    budget = RetryBudget(capacity=2, window_s=60)

    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
    assert budget.remaining() == 0

    budget.reset()
    assert budget.remaining() == 2


async def test_abortable_sleep_returns_immediately_on_signal() -> None:
    signal = asyncio.Event()
    signal.set()

    loop = asyncio.get_running_loop()
    started = loop.time()
    await abortable_sleep(5.0, signal)

    assert loop.time() - started < 0.5, "取消后不得等满退避"


async def test_abortable_sleep_waits_without_signal() -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    await abortable_sleep(0.02)

    assert loop.time() - started >= 0.015
