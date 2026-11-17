"""会话池：执行器注册与并发闸。

同一会话同时只允许一个执行体（MUST-11 状态串行化）；多端订阅不占槽位，
连接断开也不释放槽位——释放只发生在执行体结束时。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RunHandle:
    run_id: str
    task: asyncio.Task[None] | None = None
    touched_at: float = field(default_factory=time.monotonic)


class SessionPool:
    """内存态执行器表；记录本身仍由 SQLite 持有。"""

    def __init__(self, *, idle_ttl_s: float = 1800.0) -> None:
        self._handles: dict[str, RunHandle] = {}
        self._idle_ttl_s = idle_ttl_s

    def try_acquire(self, session_id: str, run_id: str) -> bool:
        existing = self._handles.get(session_id)
        if existing is not None and existing.task is not None and not existing.task.done():
            return False
        self._handles[session_id] = RunHandle(run_id=run_id)
        return True

    def attach_task(self, session_id: str, task: asyncio.Task[None]) -> None:
        handle = self._handles.get(session_id)
        if handle is not None:
            handle.task = task
            handle.touched_at = time.monotonic()

    def release(self, session_id: str) -> None:
        self._handles.pop(session_id, None)

    def active_run(self, session_id: str) -> str | None:
        handle = self._handles.get(session_id)
        if handle is None:
            return None
        if handle.task is not None and not handle.task.done():
            return handle.run_id
        return None

    def sweep(self, *, now: float | None = None) -> list[str]:
        """回收已结束且超过 TTL 的句柄，返回被回收的会话 id。"""
        current = time.monotonic() if now is None else now
        stale = [
            session_id
            for session_id, handle in self._handles.items()
            if (handle.task is None or handle.task.done())
            and current - handle.touched_at >= self._idle_ttl_s
        ]
        for session_id in stale:
            self._handles.pop(session_id, None)
        return stale

    def clear(self) -> None:
        self._handles.clear()
