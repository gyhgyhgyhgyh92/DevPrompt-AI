"""F-205 档位裁定：信息状态决定最高可输出档位（MUST-28 不越级输出）。"""

from __future__ import annotations

from typing import Literal


def resolve_level(*, has_symbol: bool, facts_complete: bool) -> Literal["A", "B", "C"]:
    """取证完成（七项全过且置信度达标）→ C；有符号定位 → B；原始模糊句 → A。"""
    if facts_complete:
        return "C"
    if has_symbol:
        return "B"
    return "A"


def expand_levels(level: Literal["A", "B", "C"]) -> list[Literal["A", "B", "C"]]:
    """MUST-28 附注：可输出档位为从 A 起的前缀——A→["A"]、B→["A","B"]、C→["A","B","C"]。

    generate_variants 的 levels 参数由调用方以本函数从 resolve_level 的结果推导
    （仅 A 档=单套，三套同调不适用；escape/护栏保守路径直接请求 ["A"]）。
    """
    order: tuple[Literal["A", "B", "C"], ...] = ("A", "B", "C")
    return list(order[: order.index(level) + 1])
