"""重试预算与退避（移植天枢 retry-engine / retry-budget 的核心）。

要点：
- 指数退避 + 抖动，封顶 30s；
- **共享 RetryBudget**：provider 重试与 agent 重连共用同一实例，避免 3×3 相乘；
- 等待可被 abort 打断，取消不必等满退避。
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    jitter_ratio: float = 0.5
    max_attempts: int = 3


DEFAULT_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy()


def next_delay(attempt: int, policy: RetryPolicy | None = None) -> float:
    """第 ``attempt`` 次重试前的等待秒数（attempt 从 1 开始）。"""
    resolved = policy if policy is not None else DEFAULT_RETRY_POLICY
    base: float = min(resolved.base_delay_s * (2 ** max(0, attempt - 1)), resolved.max_delay_s)
    return base + float(random.random()) * resolved.jitter_ratio * base


class RetryBudget:
    """滑动窗口配额：耗尽后调用方必须放弃，而不是继续叠加重试。"""

    def __init__(self, *, capacity: int = 5, window_s: float = 60.0) -> None:
        self._capacity = capacity
        self._window_s = window_s
        self._taken: list[float] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_s
        self._taken = [t for t in self._taken if t > cutoff]

    def take(self) -> bool:
        now = time.monotonic()
        self._prune(now)
        if len(self._taken) >= self._capacity:
            return False
        self._taken.append(now)
        return True

    def remaining(self) -> int:
        self._prune(time.monotonic())
        return max(0, self._capacity - len(self._taken))

    def reset(self) -> None:
        self._taken.clear()


async def abortable_sleep(seconds: float, signal: asyncio.Event | None = None) -> None:
    """等待 ``seconds``，``signal`` 置位时立即返回（不抛异常，由调用方判断）。"""
    if signal is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(signal.wait(), timeout=seconds)
    except TimeoutError:
        return
