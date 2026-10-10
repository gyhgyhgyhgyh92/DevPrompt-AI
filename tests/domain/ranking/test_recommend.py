"""F-404 推荐标记测试：MUST-27 五条优先级 + 双阈值边界（SHOULD-10）。

条件溯源（每条用例名含 case 编号）：
  ① top conf < 0.6 → 不标  ② 任一档 conf < 0.4 → 不标  ③ d < 0.12 → 不标
  ④ d ≥ 0.5 → 标  ⑤ 0.12 ≤ d < 0.5 → 标 + 「分差较小」
"""

from typing import Literal

import pytest

from devprompt_ai.domain.decision.port import VariantScore
from devprompt_ai.domain.ranking.recommend import RecommendationResult, decide_mark


def _entry(
    variant: Literal["A", "B", "C"],
    confidence: float,
    total: float,
    score: int = 4,
) -> tuple[VariantScore, float]:
    """构造 (档位评分, 加权总分) 对——总分由调用方按 F-403 合成（decide_mark 契约）。"""
    return (VariantScore(variant=variant, score=score, confidence=confidence), total)


def test_decide_mark_requires_two_variants() -> None:
    # MUST-28：单套不计算 d，调用方（service）保证；本函数违规输入即抛
    with pytest.raises(ValueError):
        decide_mark([_entry("A", 0.9, 0.8)])


def test_decide_mark_rejects_empty() -> None:
    with pytest.raises(ValueError):
        decide_mark([])


def test_case1_top_conf_below_min_no_mark_even_with_large_gap() -> None:
    # 条件①：最高分档 conf=0.55 < 0.6，即使 d=0.8 ≥ 0.5 也不标（置信度优先于分差）
    entries = [_entry("A", 0.55, 1.0), _entry("B", 0.9, 0.2)]
    result = decide_mark(entries)
    assert result.marked is False
    assert "置信度不足" in result.reason
    assert "建议人工选择" in result.reason


def test_case1_reason_carries_top_conf_value() -> None:
    entries = [_entry("A", 0.55, 1.0), _entry("B", 0.9, 0.2)]
    result = decide_mark(entries)
    assert "0.55" in result.reason  # 带 top conf 值
    assert result.confidence == 0.55


def test_case2_any_conf_below_min_no_mark() -> None:
    # 条件②：任一档 conf=0.35 < 0.4 → 不标，reason 带最低 conf 值
    entries = [_entry("A", 0.9, 1.0), _entry("B", 0.35, 0.8), _entry("C", 0.9, 0.5)]
    result = decide_mark(entries)
    assert result.marked is False
    assert "0.35" in result.reason
    assert "置信度不足" in result.reason


def test_case2_overrides_large_gap_priority() -> None:
    # 优先级压序：conf<0.4 与 d≥0.5 同时满足 → 命中条件②，reason 为置信度文案（非正向标记）
    entries = [_entry("A", 0.9, 1.0), _entry("B", 0.35, 0.2)]  # d=0.8 ≥ 0.5
    result = decide_mark(entries)
    assert result.marked is False
    assert "置信度不足" in result.reason


def test_case1_beats_case2_priority() -> None:
    # 优先级压序：top conf 0.55<0.6 且低档 0.3<0.4 → 条件①先命中，reason 带 top 值
    entries = [_entry("A", 0.55, 1.0), _entry("B", 0.3, 0.2)]
    result = decide_mark(entries)
    assert result.marked is False
    assert "0.55" in result.reason
    assert "0.3" not in result.reason  # 条件②文案未生效（命中即止）


def test_case3_gap_below_soft_no_mark() -> None:
    # 条件③：置信度充足但 d=0.11 < 0.12 → 不标
    entries = [_entry("A", 0.9, 0.91), _entry("B", 0.9, 0.8)]  # gap = 0.10999999999999999
    result = decide_mark(entries)
    assert result.marked is False
    assert result.reason == "三套适配度接近，建议人工选择"


def test_boundary_d_0_12_marks_with_small_gap() -> None:
    # 边界（MUST-27 条件⑤）：0.12 ≤ d < 0.5 含左端点 → d==0.12 标 + 「分差较小」
    # 注：任务清单「d==0.12 不标」与 MUST-27 条件③（严格小于）冲突，按宪法实现
    entries = [_entry("A", 0.9, 0.92), _entry("B", 0.9, 0.8)]  # gap == 0.12 精确
    result = decide_mark(entries)
    assert result.marked is True
    assert result.reason == "分差较小"


def test_boundary_d_0_5_marks_hard() -> None:
    # 边界（MUST-27 条件④）：d ≥ 0.5 含右端点 → d==0.5 标、无「分差较小」附注
    entries = [_entry("A", 0.9, 1.0), _entry("B", 0.9, 0.5)]  # gap == 0.5 精确
    result = decide_mark(entries)
    assert result.marked is True
    assert result.reason == ""


def test_case4_hard_gap_marks_clean() -> None:
    # 条件④：d=0.8 ≥ 0.5 → 标，无附注
    entries = [_entry("C", 0.9, 1.0), _entry("A", 0.9, 0.2)]
    result = decide_mark(entries)
    assert result.marked is True
    assert result.reason == ""
    assert result.gap == 0.8
    assert result.variant == "C"


def test_case5_soft_gap_marks_with_small_gap_note() -> None:
    # 条件⑤：0.12 ≤ d=0.3 < 0.5 → 标 + 附「分差较小」
    entries = [_entry("B", 0.9, 1.0), _entry("A", 0.9, 0.7)]  # gap = 0.30000000000000004
    result = decide_mark(entries)
    assert result.marked is True
    assert result.reason == "分差较小"


def test_result_fields_variant_and_confidence() -> None:
    # F-404 输出：推荐项 = 最高总分档位，置信度附该档数值
    entries = [_entry("C", 0.85, 1.0), _entry("A", 0.9, 0.2)]
    result: RecommendationResult = decide_mark(entries)
    assert result.variant == "C"
    assert result.confidence == 0.85
    assert result.marked is True


def test_input_order_does_not_affect_result() -> None:
    # 按总分降序取 top，与输入顺序无关
    forward = decide_mark([_entry("A", 0.9, 1.0), _entry("B", 0.9, 0.2)])
    backward = decide_mark([_entry("B", 0.9, 0.2), _entry("A", 0.9, 1.0)])
    assert (forward.variant, forward.marked, forward.reason) == (
        backward.variant,
        backward.marked,
        backward.reason,
    )
