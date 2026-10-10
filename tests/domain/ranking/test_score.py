"""F-403 加权总分测试：手工验算 + 权重校验边界（SHOULD-10）。"""

import pytest

from devprompt_ai.domain.errors import ConfigurationError, DevPromptError
from devprompt_ai.domain.ranking.score import (
    normalize_fit,
    validate_weights,
    weighted_total,
)


def test_weighted_total_manual_0_8_0_7() -> None:
    # SHOULD-10 手工验算：0.6×0.8 + 0.4×0.7 = 0.48 + 0.28 = 0.76
    assert weighted_total(0.8, 0.7) == 0.76


def test_weighted_total_manual_0_25_0_9() -> None:
    # SHOULD-10 手工验算：0.6×0.25 + 0.4×0.9 = 0.15 + 0.36 = 0.51
    assert weighted_total(0.25, 0.9) == 0.51


def test_weighted_total_default_weights_are_0_6_0_4() -> None:
    # MUST-27 公式固定系数：总分 = 0.6×适配度 + 0.4×偏好匹配度
    assert weighted_total(1.0, 0.0) == 0.6
    assert weighted_total(0.0, 1.0) == 0.4


def test_weighted_total_custom_weights() -> None:
    assert weighted_total(1.0, 0.0, w_fit=0.5, w_pref=0.5) == 0.5


def test_weighted_total_clamps_above_one() -> None:
    # 返回前 clip01（防御超界输入 / 浮点溢出）
    assert weighted_total(1.5, 1.0, w_fit=1.0, w_pref=0.0) == 1.0


def test_weighted_total_clamps_below_zero() -> None:
    assert weighted_total(-0.5, 0.0, w_fit=1.0, w_pref=0.0) == 0.0


def test_validate_weights_accepts_sum_one() -> None:
    validate_weights(0.6, 0.4)  # 不抛即通过
    validate_weights(0.0, 1.0)


def test_validate_weights_rejects_off_sum() -> None:
    with pytest.raises(ConfigurationError):
        validate_weights(0.6, 0.3)


def test_validate_weights_error_code_9002() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        validate_weights(0.6, 0.3)
    assert exc_info.value.code == 9002


def test_validate_weights_is_domain_error() -> None:
    # 语义异常体系：ConfigurationError ⊂ DevPromptError（架构文档 §3.4）
    assert issubclass(ConfigurationError, DevPromptError)


def test_validate_weights_tolerance_within() -> None:
    # 1e-9 容差内（浮点和误差 5e-10）不抛
    validate_weights(0.5 + 5e-10, 0.5)


def test_validate_weights_tolerance_near_edge() -> None:
    # 边界语义：abs(和 − 1.0) > 1e-9 才抛。浮点下「恰等于 1e-9」的求和误差
    # 可能越界（0.5+1e-9 实测 > 1e-9），故取容差内近界值 9e-10 验证不抛
    validate_weights(0.5 + 9e-10, 0.5)


def test_validate_weights_tolerance_beyond() -> None:
    with pytest.raises(ConfigurationError):
        validate_weights(0.5 + 1e-8, 0.5)


def test_normalize_fit_scale() -> None:
    # F-401 归一化：适配度 = 分数 / 4
    assert normalize_fit(0) == 0.0
    assert normalize_fit(1) == 0.25
    assert normalize_fit(2) == 0.5
    assert normalize_fit(4) == 1.0
