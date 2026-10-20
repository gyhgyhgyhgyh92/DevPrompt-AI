"""F-403 总分测试（2026-10-21 起为纯适配度：偏好记忆已移除）。"""

from devprompt_ai.domain.ranking.score import clip01, normalize_fit, weighted_total


def test_normalize_fit_maps_five_scale_to_unit() -> None:
    assert normalize_fit(4) == 1.0
    assert normalize_fit(2) == 0.5
    assert normalize_fit(0) == 0.0


def test_weighted_total_is_fit_itself() -> None:
    """总分 = 适配度（不再有 0.6/0.4 加权）。"""
    assert weighted_total(0.8) == 0.8
    assert weighted_total(0.75) == 0.75


def test_total_is_clipped_to_unit_range() -> None:
    assert weighted_total(1.4) == 1.0
    assert weighted_total(-0.2) == 0.0
    assert clip01(2.0) == 1.0
