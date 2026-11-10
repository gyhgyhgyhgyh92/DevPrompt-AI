"""运行时模型参数归一与原生映射（纯函数，零 I/O，MUST-06）。

职责边界：
- **只做参数语义转换**，不读配置、不读注册表、不发请求；
- effort 的合法值域由调用方（`model_spec` / 动态目录）提供；
- 原生供应商的 budget 映射集中在此，避免 service 与 adapters 各写一份。

为什么需要单独一层：`reasoning_effort` 是 OpenAI 兼容协议的扩展字段，而 Anthropic /
Gemini 原生协议没有同名字段；把映射写在适配器里会导致「同一档位在不同适配器含义不同」，
且无法被单测覆盖。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

#: 各厂商 effort 词表的超集。具体模型只允许其中已登记的子集。
CANONICAL_EFFORTS: Final[tuple[str, ...]] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

#: Anthropic 扩展思考预算（token）。`none` 表示关闭，不进入预算表。
ANTHROPIC_THINKING_BUDGET: Final[dict[str, int]] = {
    "minimal": 1_024,
    "low": 2_048,
    "medium": 8_192,
    "high": 16_384,
    "xhigh": 24_576,
    "max": 32_768,
}

#: Gemini 思考预算（token）。`none` = 0 表示关闭；具体模型是否接受 0 由能力位保证。
GEMINI_THINKING_BUDGET: Final[dict[str, int]] = {
    "none": 0,
    "minimal": 512,
    "low": 1_024,
    "medium": 4_096,
    "high": 8_192,
    "xhigh": 16_384,
    "max": 24_576,
}

#: Anthropic 扩展思考的最小预算；低于该值直接降级为 disabled。
_ANTHROPIC_MIN_BUDGET: Final[int] = 1_024
#: 给最终回答预留的输出 token，避免 budget 吃掉整个 max_tokens。
_ANTHROPIC_OUTPUT_RESERVE: Final[int] = 1_024


def resolve_effort(raw: str, allowed: Sequence[str]) -> str | None:
    """把用户选择解析为可下发的 effort。

    规则（与计划 §4.1 一致）：

    - 显式值：合法（在 ``allowed`` 内，或 ``allowed`` 为空表示能力位未知）则原样返回；
      明确非法返回 ``None``（运行时忽略，不让配置脏数据变成 400）。
    - 空值：仅当模型登记了 ``none`` 时解析为 ``"none"``（真正关闭思考）；
      否则返回 ``None``（不下发，跟随供应商默认）。

    :param raw: 注册表里的原始字符串（可能为空）
    :param allowed: 该模型登记的 effort 集合；空表示未登记
    """
    candidate = raw.strip().lower()
    if candidate:
        if allowed and candidate not in allowed:
            return None
        return candidate
    if "none" in allowed:
        return "none"
    return None


def anthropic_thinking(effort: str, max_tokens: int) -> dict[str, object] | None:
    """把 effort 映射为 Anthropic Messages 的 ``thinking`` 字段。

    - 未给 effort → ``None``（不设置，走供应商默认）
    - ``none`` → ``{"type": "disabled"}``
    - 其它 → ``{"type": "enabled", "budget_tokens": N}``

    Anthropic 的硬约束是 ``budget_tokens < max_tokens``；此外还要给最终回答留出空间，
    否则 ``max_tokens=4096`` 配 ``budget=4095`` 只剩 1 个输出 token。预算不足时
    降级为 disabled，而不是发一个必然 400 或必然截断的请求。
    """
    key = effort.strip().lower()
    if not key:
        return None
    if key == "none":
        return {"type": "disabled"}
    budget = ANTHROPIC_THINKING_BUDGET.get(key)
    if budget is None or max_tokens <= _ANTHROPIC_MIN_BUDGET + _ANTHROPIC_OUTPUT_RESERVE:
        return {"type": "disabled"}
    capped = min(budget, max_tokens - _ANTHROPIC_OUTPUT_RESERVE)
    if capped < _ANTHROPIC_MIN_BUDGET:
        return {"type": "disabled"}
    return {"type": "enabled", "budget_tokens": capped}


def gemini_thinking_budget(effort: str) -> int | None:
    """把 effort 映射为 Gemini ``thinking_config.thinking_budget``。

    未给 effort 或未知值 → ``None``（不设置）；``none`` → 0（关闭）。
    """
    key = effort.strip().lower()
    if not key:
        return None
    return GEMINI_THINKING_BUDGET.get(key)
