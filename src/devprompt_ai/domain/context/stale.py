"""陈旧轮判定：只回收「已被取代」或「后续再未引用」的旧工具输出。

两道守卫缺一不可：
- 滞后 3 步——刚产生的结果可能马上要用；
- 后缀 >8000 token 不剪——剪掉会让后续前缀失效，得不偿失。
"""

from __future__ import annotations

from typing import Final

LAG_STEPS: Final[int] = 3
MIN_CONTENT_CHARS: Final[int] = 500
SUFFIX_TOKEN_LIMIT: Final[int] = 8_000


def is_stale(
    *,
    content_chars: int,
    lag_steps: int,
    suffix_tokens: int,
    superseded: bool = False,
    referenced: bool = True,
) -> bool:
    """返回 True 表示这条旧输出可以被回收。"""
    if lag_steps < LAG_STEPS:
        return False
    if content_chars < MIN_CONTENT_CHARS:
        return False
    if suffix_tokens > SUFFIX_TOKEN_LIMIT:
        return False
    return superseded or not referenced
