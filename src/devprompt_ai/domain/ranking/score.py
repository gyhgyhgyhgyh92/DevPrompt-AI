"""F-403 总分：2026-10-21 起为「纯适配度」（偏好记忆已移除，MUST-27 同步修订）。"""

from __future__ import annotations

from typing import Final

# F-401 五档刻度 0..4 的归一化分母。
FIT_SCALE: Final[float] = 4.0


def clip01(value: float) -> float:
    """把任意实数夹到 [0, 1]（原 preference.py，随偏好层移除后落在这里）。"""
    return max(0.0, min(1.0, value))


def normalize_fit(score: int) -> float:
    """F-401 归一化：适配度 = 决策层五档分数 / 4，值域 [0, 1]。"""
    return score / FIT_SCALE


def weighted_total(fit: float) -> float:
    """总分（保留函数名以免调用点大改）：纯适配度。"""
    return clip01(fit)
