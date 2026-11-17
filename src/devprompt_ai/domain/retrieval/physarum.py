"""访问强化（I6）：相邻文件访问会强化边权，长期不用的边自然衰减。

这是「跨会话的隐性习惯」：常一起改的文件，未来更可能一起改。
权重有上下界，避免一次热点访问把图烧死。
"""

from __future__ import annotations

import math
from typing import Final

_DEFAULT_GROWTH: Final[float] = 0.1
_DEFAULT_GAMMA: Final[float] = 1.0
_DEFAULT_TAU: Final[float] = 300.0
_MAX_WEIGHT: Final[float] = 5.0
_PRUNE_THRESHOLD: Final[float] = 0.05


def reinforce(
    weight: float,
    *,
    flow: float = 1.0,
    dt: float = 0.0,
    growth: float = _DEFAULT_GROWTH,
    gamma: float = _DEFAULT_GAMMA,
    tau: float = _DEFAULT_TAU,
) -> float:
    """电导方程：`w + growth·flow^γ − w(1 − e^(−dt/τ))`。"""
    decay_amount = weight if tau <= 0 else weight * (1 - math.exp(-max(0.0, dt) / tau))
    updated = weight + growth * (max(0.0, flow) ** gamma) - decay_amount
    result: float = min(_MAX_WEIGHT, max(0.0, updated))
    return result


def decay(weight: float, *, dt: float, tau: float = _DEFAULT_TAU) -> float:
    if tau <= 0:
        return 0.0
    value: float = weight * math.exp(-max(0.0, dt) / tau)
    return max(0.0, value)


def prune(weight: float, *, threshold: float = _PRUNE_THRESHOLD) -> float:
    """低于阈值直接归零，防止长尾边无限累积。"""
    return 0.0 if weight < threshold else weight
