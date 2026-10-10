"""F-403 加权总分：适配度归一化 + 双权重合成（纯逻辑零 I/O，MUST-06/MUST-08）。

权重默认 0.6/0.4 为 MUST-27 公式固定系数；权重配置变化时由调用方（service）
从 config 注入并先行 validate_weights，本模块不做配置读取。
"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.errors import ConfigurationError
from devprompt_ai.domain.ranking.preference import clip01

# F-403：权重之和必须为 1.0，1e-9 容差吸收浮点求和误差。
WEIGHT_SUM_TOLERANCE: Final[float] = 1e-9
DEFAULT_WEIGHT_FIT: Final[float] = 0.6
DEFAULT_WEIGHT_PREF: Final[float] = 0.4

# F-401 五档刻度 0..4 的归一化分母。
FIT_SCALE: Final[float] = 4.0


def validate_weights(w_fit: float, w_pref: float) -> None:
    """F-403 权重校验：和 ≠ 1.0（容差 1e-9）抛 ConfigurationError(9002)。"""
    if abs((w_fit + w_pref) - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ConfigurationError(
            f"权重之和必须为 1.0，实际 {w_fit} + {w_pref} = {w_fit + w_pref}",
            context={"w_fit": w_fit, "w_pref": w_pref},
        )


def normalize_fit(score: int) -> float:
    """F-401 归一化：适配度 = 决策层五档分数 / 4，值域 [0, 1]。"""
    return score / FIT_SCALE


def weighted_total(
    fit: float,
    pref: float,
    w_fit: float = DEFAULT_WEIGHT_FIT,
    w_pref: float = DEFAULT_WEIGHT_PREF,
) -> float:
    """F-403 总分 = w_fit × 适配度 + w_pref × 偏好匹配度，返回前 clip01。"""
    return clip01(w_fit * fit + w_pref * pref)
