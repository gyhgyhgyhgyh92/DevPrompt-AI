"""委派调度（K2）：分池信号量 + 文件占位 + 去重。

三道闸按顺序生效：工单可运行性（依赖/深度/范围）→ 文件占位冲突 → 分池容量。
占位在取得槽位后、执行前登记，结束必然释放（finally）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from devprompt_ai.domain.agent.delegation import conflicts
from devprompt_ai.domain.agent.profile_registry import get_profile
from devprompt_ai.domain.agent.work_order import WorkOrder, validate

T = TypeVar("T")


class DelegationCoordinator:
    def __init__(self, *, total_cap: int = 4, explore_cap: int = 2, write_cap: int = 1) -> None:
        self._total = asyncio.Semaphore(max(1, total_cap))
        self._explore = asyncio.Semaphore(max(1, explore_cap))
        self._write = asyncio.Semaphore(max(1, write_cap))
        self._inflight: set[str] = set()

    @property
    def inflight(self) -> frozenset[str]:
        return frozenset(self._inflight)

    def can_run(self, order: WorkOrder) -> bool:
        profile = get_profile(order.profile)
        if profile is None:
            return False
        try:
            validate(order, write=profile.write)
        except ValueError:
            return False
        return not conflicts(self._inflight, order.scope_files)

    async def run(
        self,
        order: WorkOrder,
        worker: Callable[[WorkOrder], Awaitable[T]],
    ) -> T:
        if not self.can_run(order):
            raise ValueError(f"工单不可运行：{order.id}")
        profile = get_profile(order.profile)
        assert profile is not None  # can_run 已保证
        pool = self._write if profile.write else self._explore
        await self._total.acquire()
        await pool.acquire()
        self._inflight.update(order.scope_files)
        try:
            return await worker(order)
        finally:
            self._inflight.difference_update(order.scope_files)
            pool.release()
            self._total.release()
