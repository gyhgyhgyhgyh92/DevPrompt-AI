"""F-805 成本监控：单次优化的 token 用量累计（LLM 实际）。

累计器以 ContextVar 承载：harness/llm 在每次外部调用后累加，service 在快照组装时
一次性取用（take）并清零——同一请求内多次调用正确汇总，跨请求不重复计数
（每次请求在独立上下文中，累计器从 0 起步）。
"""

from __future__ import annotations

from contextvars import ContextVar

_LLM_TOKENS: ContextVar[int] = ContextVar("cost_llm_tokens", default=0)


def add_llm_tokens(total: int) -> None:
    """累加一次 LLM 调用的 token 用量（来源：SDK usage 实际值）。"""
    if total:
        _LLM_TOKENS.set(_LLM_TOKENS.get() + total)


def take_llm_tokens() -> int:
    """取自上次取用以来累计的 llm token 用量并清零。"""
    llm_tokens = _LLM_TOKENS.get()
    _LLM_TOKENS.set(0)
    return llm_tokens
