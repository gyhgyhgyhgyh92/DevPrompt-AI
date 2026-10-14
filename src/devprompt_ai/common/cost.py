"""F-805 成本监控：单次优化的 token 用量累计（LLM 实际 / Jev 估算）。

累计器以 ContextVar 承载：harness/llm 与 decision/jev 在每次外部调用后各自累加，
service 在快照组装时一次性取用（take）并清零——同一请求内多次调用正确汇总，
跨请求不重复计数（每次请求在独立上下文中，累计器从 0 起步）。

落点选 common/ 而非 harness/ 或 decision/：Jev 属可选 extra（typesafe-sdk），
service 不得为读取该累计量而在顶层 import decision.jev（未装 extra 的环境会 ImportError）；
common 为最低层工具模块，harness/decision/service 均可安全依赖。
"""

from __future__ import annotations

from contextvars import ContextVar

_LLM_TOKENS: ContextVar[int] = ContextVar("cost_llm_tokens", default=0)
_JEV_TOKENS: ContextVar[int] = ContextVar("cost_jev_tokens", default=0)


def add_llm_tokens(total: int) -> None:
    """累加一次 LLM 调用的 token 用量（来源：SDK usage 实际值）。"""
    if total:
        _LLM_TOKENS.set(_LLM_TOKENS.get() + total)


def add_jev_tokens(estimated: int) -> None:
    """累加一次 Jev 调用的 token 用量（Jev 无 usage 回传，按 state 粗估，来源标注为估算）。"""
    if estimated:
        _JEV_TOKENS.set(_JEV_TOKENS.get() + estimated)


def take_tokens() -> tuple[int, int]:
    """取自上次取用以来累计的 (llm_tokens, jev_tokens) 并清零。"""
    llm_tokens, jev_tokens = _LLM_TOKENS.get(), _JEV_TOKENS.get()
    _LLM_TOKENS.set(0)
    _JEV_TOKENS.set(0)
    return llm_tokens, jev_tokens
