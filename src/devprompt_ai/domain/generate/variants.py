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
