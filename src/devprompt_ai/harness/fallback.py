"""主备切换（G6）：主客户端失败一次即切备，不重放已失败的请求。

只做「同一操作用备客户端再跑一次」；重试次数仍由 RetryBudget 统一约束，
避免 fallback × retry 相乘。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class FallbackClient(Generic[T]):
    def __init__(self, primary: T, backup: T | None = None) -> None:
        self._primary = primary
        self._backup = backup
        self._using_backup = False

    @property
    def using_backup(self) -> bool:
        return self._using_backup

    def current(self) -> T:
        return self._backup if self._using_backup and self._backup is not None else self._primary

    async def call(self, operation: Callable[[T], Awaitable[R]]) -> R:
        """先用当前客户端；失败且尚未切备时切备重试一次。"""
        try:
            return await operation(self.current())
        except Exception:
            if self._backup is None or self._using_backup:
                raise
            self._using_backup = True
            return await operation(self._backup)
