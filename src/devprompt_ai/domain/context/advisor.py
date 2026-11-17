"""缓存顾问（纯函数）：命中率高且压力不大时，把压缩推迟到下一个用户边界。

公式：`protection = 近期命中率 × (1 − 压力)`，≥0.45 就推迟。
压力上来后即使全命中也要压——1M 窗口下的 OOM 风险大于重建成本。
"""

from __future__ import annotations

from typing import Final

#: 达到该档位（reactive/ceiling）时从不推迟。
_NEVER_DELAY_TIER: Final[int] = 3
_PROTECTION_THRESHOLD: Final[float] = 0.45


def should_delay(
    *,
    recent_hit_rate: float,
    pressure: float,
    tier: int,
) -> bool:
    """返回 True 表示「先别压」。"""
    if tier >= _NEVER_DELAY_TIER:
        return False
    hit = min(1.0, max(0.0, recent_hit_rate))
    load = min(1.0, max(0.0, pressure))
    return hit * (1.0 - load) >= _PROTECTION_THRESHOLD
