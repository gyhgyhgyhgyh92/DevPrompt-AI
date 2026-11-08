"""压缩决策树（纯函数，零 I/O）。

顺序：ceiling → 1M 阶梯 → 精度带 → 缓存类型分档。
只看三个纯输入：占用率、上下文窗口、provider 缓存类型——不关心具体供应商。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class CompactAction(str, Enum):
    NONE = "none"
    MICRO = "micro"
    COLLAPSE = "collapse"
    PRUNE = "prune"
    STALE = "stale"
    PARTIAL_LLM = "partial-llm"
    FULL_LLM = "full-llm"
    CHECKPOINT = "checkpoint"


class CacheKind(str, Enum):
    """provider 的前缀缓存能力，决定压缩档位。"""

    NONE = "none"
    AUTOMATIC = "automatic"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True)
class CompactDecision:
    action: CompactAction
    tier: int = 0
    force: bool = False
    reason: str = ""

    @property
    def should_compact(self) -> bool:
        return self.action is not CompactAction.NONE


#: 缓存的越好，越要少压（压一次就毁掉已付费前缀）。
_TIER_RATIOS: Final[dict[CacheKind, tuple[float, float, float]]] = {
    CacheKind.EXPLICIT: (0.72, 0.86, 0.92),
    CacheKind.AUTOMATIC: (0.60, 0.78, 0.88),
    CacheKind.NONE: (0.50, 0.70, 0.84),
}

CEILING_RATIO: Final[float] = 0.95
#: 1M 窗口的 LLM 阶梯（partial / full）；按量计费 + 精确缓存时门槛抬高。
_PARTIAL_1M: Final[float] = 0.60
_FULL_1M: Final[float] = 0.75
_PARTIAL_1M_EXPENSIVE: Final[float] = 0.75
_FULL_1M_EXPENSIVE: Final[float] = 0.85


def ratios_for(cache_kind: CacheKind) -> tuple[float, float, float]:
    """返回 (watch, compact, reactive) 三个比例。"""
    return _TIER_RATIOS[cache_kind]


def precision_ceiling(window: int) -> float | None:
    """精度天花板：窗口越大，模型注意力衰减越早，需更早回收。"""
    if window >= 500_000:
        return 0.70
    if window >= 200_000:
        return 0.55
    return None


def decide_compact_action(
    ratio: float,
    *,
    window: int,
    cache_kind: CacheKind,
    per_token_billing: bool = False,
) -> CompactDecision:
    """按占用率给出压缩动作。"""
    if ratio >= CEILING_RATIO:
        action = CompactAction.CHECKPOINT if window >= 1_000_000 else CompactAction.MICRO
        return CompactDecision(action, tier=4, force=True, reason="ceiling")

    if window >= 1_000_000:
        partial = _PARTIAL_1M_EXPENSIVE if per_token_billing else _PARTIAL_1M
        full = _FULL_1M_EXPENSIVE if per_token_billing else _FULL_1M
        if ratio >= full:
            return CompactDecision(CompactAction.FULL_LLM, tier=3, reason="1m-full")
        if ratio >= partial:
            return CompactDecision(CompactAction.PARTIAL_LLM, tier=3, reason="1m-partial")

    ceiling = precision_ceiling(window)
    if ceiling is not None and ratio >= ceiling:
        return CompactDecision(CompactAction.STALE, tier=2, reason="precision-band")

    watch, compact, reactive = ratios_for(cache_kind)
    if ratio >= reactive:
        return CompactDecision(CompactAction.MICRO, tier=3, reason="reactive")
    if ratio >= compact:
        return CompactDecision(CompactAction.MICRO, tier=2, reason="compact")
    if ratio >= watch:
        return CompactDecision(CompactAction.MICRO, tier=1, reason="watch")
    return CompactDecision(CompactAction.NONE, reason="below-watch")
