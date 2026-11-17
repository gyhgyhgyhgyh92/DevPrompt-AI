"""压缩经济性否决门（纯函数）：这次重写够本吗？

为什么要否决：per-token 计费下重写历史要重新支付 prefill，压得太少等于纯亏。
天枢把「回收量门槛」按 `计费 × 缓存 × 窗口档` 算成可比较的数字，这里沿用同一口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from devprompt_ai.domain.context.compact_policy import CacheKind


class Billing(str, Enum):
    PER_TOKEN = "per-token"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True, slots=True)
class ReclaimFloor:
    """必须回收的最小 token 与占比；两者同时满足才够本。"""

    min_tokens: int
    min_ratio: float

    @property
    def floor_tokens(self) -> int:
        return self.min_tokens


@dataclass(frozen=True, slots=True)
class ReclaimVerdict:
    worthwhile: bool
    reason: str
    reclaimed: int


def reclaim_floor(
    *,
    billing: Billing,
    cache_kind: CacheKind,
    window: int,
) -> ReclaimFloor:
    large = window >= 500_000
    exact_cache = cache_kind is CacheKind.EXPLICIT
    if billing is Billing.PER_TOKEN and exact_cache and large:
        return ReclaimFloor(min_tokens=max(32_768, int(window * 0.05)), min_ratio=0.05)
    if billing is Billing.PER_TOKEN and exact_cache:
        return ReclaimFloor(min_tokens=max(8_192, int(window * 0.03)), min_ratio=0.03)
    return ReclaimFloor(min_tokens=max(4_096, int(window * 0.01)), min_ratio=0.01)


def judge_reclaim(
    *,
    before_tokens: int,
    after_tokens: int,
    floor: ReclaimFloor,
    force: bool = False,
) -> ReclaimVerdict:
    """force（OOM/超窗）不受否决门约束。"""
    if force:
        return ReclaimVerdict(True, "forced", max(0, before_tokens - after_tokens))
    reclaimed = before_tokens - after_tokens
    if reclaimed <= 0:
        return ReclaimVerdict(False, "no-reclaim", 0)
    if reclaimed < floor.min_tokens:
        return ReclaimVerdict(False, "below-token-floor", reclaimed)
    if before_tokens > 0 and reclaimed / before_tokens < floor.min_ratio:
        return ReclaimVerdict(False, "below-ratio-floor", reclaimed)
    return ReclaimVerdict(True, "worthwhile", reclaimed)


#: 默认档位：订阅制只付延迟，门槛最低。
DEFAULT_FLOOR: Final[ReclaimFloor] = ReclaimFloor(min_tokens=4_096, min_ratio=0.01)
