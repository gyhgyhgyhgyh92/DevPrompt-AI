"""F-503 update_vector 五类规则测试（开放决策 #1 定稿公式，用户裁定 2026-10-10）。

五类：①连续采纳 C 向特征移动 ②跳过趋向中性（精确断言）③编辑采纳弱于直接采纳
④裁剪边界 ⑤EMA 步进 10%。
"""

import pytest

from devprompt_ai.domain.ranking.ports import AdoptionRecord, VariantLevel
from devprompt_ai.domain.ranking.preference import (
    FEATURE_TABLE,
    INITIAL_PREFERENCE,
    update_vector,
)

ALL_DIMS = ("detail_level", "include_diff", "specify_tests", "max_files_norm")


def _adopt(variant: VariantLevel, *, edited: bool = False, ratio: float = 0.0) -> AdoptionRecord:
    return AdoptionRecord(
        user_id="u",
        session_id="s",
        variant=variant,
        edited=edited,
        edited_text_ratio=ratio,
        features=FEATURE_TABLE[variant],
    )


# ---- ① 连续采纳 C：detail_level 向 0.9（C 特征）移动 ----


def test_repeated_c_adoption_moves_toward_c_features() -> None:
    v = dict(INITIAL_PREFERENCE)
    prev = v["detail_level"]
    for _ in range(30):
        v = update_vector(v, _adopt("C"))
        assert v["detail_level"] > prev  # 单调向 0.9 移动（F-503 验收）
        prev = v["detail_level"]
    assert v["detail_level"] < 0.9  # EMA 收敛不过冲
    assert v["detail_level"] == pytest.approx(0.9, abs=0.02)
    # 其余三维同步向 C 特征（0.9/0.8/1.0）方向移动
    assert v["include_diff"] > 0.5
    assert v["specify_tests"] > 0.5
    assert v["max_files_norm"] > 0.5


def test_adoption_moves_toward_feature_not_away() -> None:
    # 已处于特征值的维度不被采纳拉离（信号强度语义的自洽性）
    at_c = {"detail_level": 0.9, "include_diff": 0.5, "specify_tests": 0.5, "max_files_norm": 0.5}
    out = update_vector(at_c, _adopt("C"))
    assert out["detail_level"] == pytest.approx(0.9, abs=1e-12)


# ---- ② 跳过：趋向中性 0.5（精确断言，v ← v + (0.5−v)×0.3）----


def test_skip_regresses_toward_neutral_exact() -> None:
    above = {**INITIAL_PREFERENCE, "detail_level": 0.6}
    assert update_vector(above, None)["detail_level"] == pytest.approx(0.57, abs=1e-9)
    below = {**INITIAL_PREFERENCE, "detail_level": 0.4}
    assert update_vector(below, None)["detail_level"] == pytest.approx(0.43, abs=1e-9)
    # 采纳 A 后的 0.48（0.9×0.5+0.1×0.3），跳过一步回移 30% 差距 → 0.486
    after_a = {**INITIAL_PREFERENCE, "detail_level": 0.48}
    assert update_vector(after_a, None)["detail_level"] == pytest.approx(0.486, abs=1e-9)


def test_skip_converges_to_neutral_without_overshoot() -> None:
    v: dict[str, float] = {**INITIAL_PREFERENCE, "detail_level": 0.9}
    for _ in range(50):
        v = update_vector(v, None)
        assert 0.5 <= v["detail_level"] <= 0.9  # 单调回归，不越过中性点
    assert v["detail_level"] == pytest.approx(0.5, abs=0.01)
    assert v["include_diff"] == pytest.approx(0.5, abs=0.01)


# ---- ③ 编辑采纳弱于直接采纳（信号强度 ×(1−编辑距离占比)）----


def test_edited_adoption_weaker_than_direct() -> None:
    direct = update_vector(dict(INITIAL_PREFERENCE), _adopt("C"))
    edited = update_vector(dict(INITIAL_PREFERENCE), _adopt("C", edited=True, ratio=0.5))
    assert edited["detail_level"] == pytest.approx(0.52, abs=1e-9)  # 0.5+0.1×0.5×0.4
    assert direct["detail_level"] == pytest.approx(0.54, abs=1e-9)
    assert 0.5 < edited["detail_level"] < direct["detail_level"]  # 同向但步幅更小


def test_fully_rewritten_adoption_has_zero_signal() -> None:
    # 完全重写（占比 1.0）→ 强度 0 → 向量不动（重写不产生方向信号）
    out = update_vector(dict(INITIAL_PREFERENCE), _adopt("C", edited=True, ratio=1.0))
    assert out == dict(INITIAL_PREFERENCE)


# ---- ④ 裁剪边界（输出逐维 clip01，超界输入同样设防）----


def test_clip01_boundary_on_update() -> None:
    over = {**INITIAL_PREFERENCE, "detail_level": 1.5}
    # 1.5 + 0.1×(0.3−1.5) = 1.38 → clip 1.0
    assert update_vector(over, _adopt("A"))["detail_level"] == 1.0
    under = {**INITIAL_PREFERENCE, "detail_level": -0.3}
    # −0.3 + (0.5−(−0.3))×0.3 = −0.06 → clip 0.0
    assert update_vector(under, None)["detail_level"] == 0.0
    top = {**INITIAL_PREFERENCE, "max_files_norm": 1.0}
    # 已在边界且特征同为 1.0 → 稳定不动
    assert update_vector(top, _adopt("C"))["max_files_norm"] == pytest.approx(1.0, abs=1e-12)


def test_output_always_within_unit_range() -> None:
    for start in (
        {},
        dict(INITIAL_PREFERENCE),
        dict.fromkeys(ALL_DIMS, 1.0),
        {"detail_level": -2.0},
    ):
        for rec in (_adopt("A"), _adopt("C", edited=True, ratio=0.7), None):
            out = update_vector(start, rec)
            assert all(0.0 <= out[d] <= 1.0 for d in ALL_DIMS)


# ---- ⑤ EMA 步进 10%（每步残余差距 ×0.9）----


def test_ema_step_is_ten_percent_of_gap() -> None:
    v1 = update_vector(dict(INITIAL_PREFERENCE), _adopt("C"))
    assert v1["detail_level"] == pytest.approx(0.54, abs=1e-9)  # 0.5 + 10%×(0.9−0.5)
    gap1 = 0.9 - v1["detail_level"]
    assert gap1 == pytest.approx((0.9 - 0.5) * 0.9, rel=1e-9)  # 残余差距 ×0.9
    v2 = update_vector(v1, _adopt("C"))
    assert (0.9 - v2["detail_level"]) == pytest.approx(gap1 * 0.9, rel=1e-9)


# ---- 纯函数性与缺维度补齐 ----


def test_update_vector_does_not_mutate_input() -> None:
    v = dict(INITIAL_PREFERENCE)
    snapshot = dict(v)
    update_vector(v, _adopt("C"))
    update_vector(v, None)
    assert v == snapshot


def test_missing_dims_default_to_neutral() -> None:
    out = update_vector({}, _adopt("C"))
    assert out["detail_level"] == pytest.approx(0.54, abs=1e-9)  # 与 INITIAL 起点等效
    out_skip = update_vector({}, None)
    assert out_skip == dict.fromkeys(ALL_DIMS, 0.5)
