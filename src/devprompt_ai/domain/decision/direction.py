"""方向分歧检测（纯函数，2026-11-07 从 service.py 抽出）。

用途：多轮里判断用户是否在表达「换个方向」，命中则本轮重新给三套方案
（``_should_offer_three``）。为什么不用 LLM：这是**触发器**而不是产出，误判为「没换方向」
只会沿用上一轮方向（降级可用），却要为每轮多付一次调用延迟；而真正的方向理解发生在
后面的研判/生成里。故保持启发式，但把词表与归一化收到单独模块里，可独立测试与扩充。

召回口径：先 casefold + 去空白标点，再按「短语包含」匹配——用户写「还是别按刚才那套了」
这类句子时，标点与语气词不该影响命中。
"""

from __future__ import annotations

import re
from typing import Final

#: 方向分歧短语（覆盖「否定上一版 / 换路线 / 调整风险偏好」三类）。
DIRECTION_CONFLICT_PHRASES: Final[tuple[str, ...]] = (
    # 否定上一版
    "推翻",
    "不要按",
    "别按",
    "别用刚才",
    "不是这个方向",
    "不是这个思路",
    "重来",
    "重新考虑",
    "换个方向",
    "换个思路",
    "换成另一种",
    "换一套",
    "另一种方案",
    # 风险偏好切换
    "走激进",
    "激进一点",
    "更激进",
    "保守一点",
    "更保守",
    "稳一点",
)

_STRIP_RE: Final[re.Pattern[str]] = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize(sentence: str) -> str:
    return _STRIP_RE.sub("", sentence.casefold())


def detect_direction_conflict(sentence: str) -> bool:
    """句子是否表达了方向分歧（空句返回 False：没有新信息就没有新方向）。"""
    normalized = _normalize(sentence)
    if normalized == "":
        return False
    return any(_normalize(phrase) in normalized for phrase in DIRECTION_CONFLICT_PHRASES)
