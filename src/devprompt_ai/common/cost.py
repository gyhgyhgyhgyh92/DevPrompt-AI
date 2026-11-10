"""F-805 成本监控：单次请求内的 token 用量聚合。

累计器以 ContextVar 承载：harness/llm 在每次外部调用后累加 total/prompt/completion/
cached，service 在快照/收尾时一次性取用并清零——同一请求内多次调用（探针/排序/生成）
正确汇总，跨请求不重复计数。

2026-11-10：从「只累计 total」扩展为全字段聚合。此前 prompt/completion 只在生成/回答后
用 `last_usage()` 记一次，探针/排序/打分的明细因此丢失，账本与快照口径不一致。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Usage:
    """一次请求内累计的 token 用量；cached 为 None 表示供应商从未返回该字段。"""

    total: int = 0
    prompt: int = 0
    completion: int = 0
    cached: int | None = None


_USAGE: ContextVar[Usage | None] = ContextVar("llm_usage", default=None)


def _non_negative(value: int | None) -> int:
    return max(0, int(value or 0))


def add_llm_usage(
    total: int | None,
    prompt: int | None = None,
    completion: int | None = None,
    cached: int | None = None,
) -> None:
    """累加一次 LLM 调用的 token 用量；负值按 0 处理，cached=None 不覆盖已有值。"""
    current = _USAGE.get() or Usage()
    cached_total = current.cached
    if cached is not None:
        cached_total = _non_negative(current.cached) + _non_negative(cached)
    _USAGE.set(
        Usage(
            total=current.total + _non_negative(total),
            prompt=current.prompt + _non_negative(prompt),
            completion=current.completion + _non_negative(completion),
            cached=cached_total,
        )
    )


def take_llm_usage() -> Usage:
    """取走上一次取用以来的聚合用量并清零。"""
    usage = _USAGE.get() or Usage()
    _USAGE.set(None)
    return usage


def add_llm_tokens(total: int) -> None:
    """兼容旧调用方：只累计 total。"""
    add_llm_usage(total)


def take_llm_tokens() -> int:
    """兼容旧调用方：返回并清零 total。"""
    return take_llm_usage().total
