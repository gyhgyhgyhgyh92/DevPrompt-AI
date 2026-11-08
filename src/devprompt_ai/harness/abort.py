"""可中断等待（A6）：把「等待某个 await」与「取消信号」竞速。

与 `asyncio.wait_for` 的区别：这里等的是**外部信号**（用户取消/run 结束），
而不是时间；命中时抛 `CancelledError`，让上层走统一的取消收尾路径。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

T = TypeVar("T")


async def reject_on_abort(
    awaitable: Awaitable[T],
    signal: asyncio.Event | None,
    *,
    label: str = "",
) -> T:
    """`signal` 置位时立即取消等待并抛出 CancelledError；未提供信号时直接等待。"""
    if signal is None:
        return await awaitable
    if signal.is_set():
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError(f"aborted before start: {label}")

    task: asyncio.Future[T] = asyncio.ensure_future(awaitable)
    waiter: asyncio.Future[bool] = asyncio.ensure_future(signal.wait())
    pending: set[asyncio.Future[Any]] = {task, waiter}
    try:
        done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        task.cancel()
        raise asyncio.CancelledError(f"aborted while waiting: {label}")
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()
