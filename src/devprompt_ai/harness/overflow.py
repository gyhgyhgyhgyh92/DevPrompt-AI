"""超窗处理（A8）：请求级预算不足时「压一次 → 重发一次」。

只重试**一类**错误：上下文超限。其它错误照常抛出，避免把真实故障当成超窗反复重试。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final, TypeVar

from devprompt_ai.domain.context.budget import RequestBudgetError

T = TypeVar("T")

_OVERFLOW_MARKERS: Final[tuple[str, ...]] = (
    "context length",
    "context_length_exceeded",
    "maximum context",
    "too many tokens",
    "prompt is too long",
    "input length",
    "reduce the length",
)


def is_context_overflow(exc: BaseException) -> bool:
    """识别供应商返回的超窗错误（按文案，不绑具体 SDK 异常类）。"""
    if isinstance(exc, RequestBudgetError):
        return True
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in _OVERFLOW_MARKERS)


async def with_overflow_retry(
    call: Callable[[], Awaitable[T]],
    *,
    compact: Callable[[], Awaitable[None]],
) -> T:
    """首次调用失败且判定为超窗时，执行一次压缩并重发；再失败即抛。"""
    try:
        return await call()
    except Exception as exc:
        if not is_context_overflow(exc):
            raise
        await compact()
        try:
            return await call()
        except Exception as second:
            raise second from exc
