"""F-402 偏好向量测试：FEATURE_TABLE 逐值溯源 + 匹配度手工验算（SHOULD-10）。"""

from devprompt_ai.domain.ranking.ports import VariantFeatures, VariantLevel
from devprompt_ai.domain.ranking.preference import (
    FEATURE_TABLE,
    INITIAL_PREFERENCE,
    clip01,
    match_score,
)

# 测试内以 str 键构造偏好向量（与 PreferenceStore.load 返回类型一致）
ALL_DIMS: tuple[str, ...] = ("detail_level", "include_diff", "specify_tests", "max_files_norm")

# F-402 功能清单原文（2026-10-10 逐值核对；注意与实施计划初稿「0.25/0.58/1.0」不同，
# 初稿值仅是 max_files_norm 单行，本表按原文分维取值）
_F402_ORIGINAL: dict[VariantLevel, VariantFeatures] = {
    "A": {"detail_level": 0.3, "include_diff": 0.5, "specify_tests": 0.2, "max_files_norm": 0.25},
    "B": {"detail_level": 0.6, "include_diff": 0.8, "specify_tests": 0.5, "max_files_norm": 0.58},
    "C": {"detail_level": 0.9, "include_diff": 0.9, "specify_tests": 0.8, "max_files_norm": 1.0},
}


def test_feature_table_has_three_variants() -> None:
    assert set(FEATURE_TABLE) == {"A", "B", "C"}


def test_feature_table_four_dims_each() -> None:
    for feat in FEATURE_TABLE.values():
        assert set(feat) == {"detail_level", "include_diff", "specify_tests", "max_files_norm"}


def test_feature_table_matches_f402_original() -> None:
    # 与功能清单 F-402「方案特征向量」表格逐值一致（D-5B-1 溯源）
    for variant, feat in _F402_ORIGINAL.items():
        assert FEATURE_TABLE[variant] == feat, f"F-402 {variant} 档特征值不一致"


def test_feature_table_values_in_unit_range() -> None:
    for feat in FEATURE_TABLE.values():
        for v in feat.values():
            assert 0.0 <= v <= 1.0


def test_initial_preference_neutral_half() -> None:
    assert INITIAL_PREFERENCE == {
        "detail_level": 0.5,
        "include_diff": 0.5,
        "specify_tests": 0.5,
        "max_files_norm": 0.5,
    }


def test_clip01_clamps_below_zero() -> None:
    assert clip01(-0.1) == 0.0


def test_clip01_clamps_above_one() -> None:
    assert clip01(1.1) == 1.0


def test_clip01_passes_through_and_edges() -> None:
    assert clip01(0.42) == 0.42
    assert clip01(0.0) == 0.0
    assert clip01(1.0) == 1.0


def test_match_score_identical_vectors_is_one() -> None:
    # 全等向量 → 1 - mean(0) = 1.0（SHOULD-10 手工验算）；pref 与 B 档特征逐值相同
    pref_b: dict[str, float] = {
        "detail_level": 0.6,
        "include_diff": 0.8,
        "specify_tests": 0.5,
        "max_files_norm": 0.58,
    }
    assert match_score(pref_b, FEATURE_TABLE["B"]) == 1.0


def test_match_score_opposite_vectors_is_zero() -> None:
    # 全反向量：feat 全 0 / pref 全 1 → 1 - mean(1) = 0.0（SHOULD-10 手工验算）
    zero_feat: VariantFeatures = {k: 0.0 for k in FEATURE_TABLE["A"]}
    one_pref = {k: 1.0 for k in ALL_DIMS}
    assert match_score(one_pref, zero_feat) == 0.0


def test_match_score_manual_calculation() -> None:
    # pref 中性 0.5 vs A 档特征：|0.5-0.3|+|0.5-0.5|+|0.5-0.2|+|0.5-0.25| = 0.75，均值 0.1875
    # 1 - 0.1875 = 0.8125
    assert match_score(dict(INITIAL_PREFERENCE), FEATURE_TABLE["A"]) == 0.8125


def test_match_score_missing_dims_default_half() -> None:
    # pref 缺维度按 0.5 补（F-402 初始中性值）
    all_half_feat = {k: 0.5 for k in FEATURE_TABLE["A"]}
    assert match_score({}, all_half_feat) == 1.0  # 全部按 0.5 补 → 差值全 0
    partial = {"detail_level": 1.0}
    # diffs = (0.5, 0, 0, 0) → mean 0.125 → 0.875
    assert match_score(partial, all_half_feat) == 0.875


def test_match_score_within_unit_range() -> None:
    for feat in FEATURE_TABLE.values():
        for pref in ({}, dict(INITIAL_PREFERENCE), {k: 1.0 for k in ALL_DIMS}):
            assert 0.0 <= match_score(pref, feat) <= 1.0
