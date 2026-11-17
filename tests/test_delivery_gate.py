"""交付证据门测试：三态优先级、不适用项不参与、RED 不阻断交付。

2026-11-11 单套输出后，门禁不再包含档位/推荐/套数语义（``can_mark_c`` /
``can_mark_recommend`` / ``variant_count`` 已删除）。
"""

from __future__ import annotations

from typing import cast

from devprompt_ai.domain.delivery.attribution import Attribution
from devprompt_ai.domain.delivery.gate import (
    DeliveryInput,
    DeliveryVerdict,
    evaluate_delivery,
)
from devprompt_ai.domain.models import FactKey, FactResult


def _fact(key: str, passed: bool, *, applicable: bool = True) -> FactResult:
    return FactResult(
        key=cast(FactKey, key),
        passed=passed,
        evidence="e",
        applicable=applicable,
    )


def _green_facts() -> list[FactResult]:
    return [
        _fact("target_file_exists", True),
        _fact("symbol_in_file", True),
        _fact("token_defined", False, applicable=False),
    ]


def test_green_when_evidence_complete() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(has_target=True, facts=_green_facts(), claim_coverage=0.9)
    )

    assert verdict.status == "GREEN"
    assert verdict.disclosure == ""
    assert verdict.tone == "ok"


def test_attribution_uncovered_impact_forces_yellow() -> None:
    """E11：影响半径里未被断言引用的文件必须披露。"""
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=0.9,
            attribution=Attribution(uncovered_impact=("src/ui/Icon.tsx", "src/api/useFoo.ts")),
        )
    )

    assert verdict.status == "YELLOW"
    assert any("影响半径" in reason for reason in verdict.reasons)


def test_attribution_absent_keeps_green() -> None:
    """未开 repo 图时无归属数据，门禁不受影响（不猜）。"""
    verdict = evaluate_delivery(
        DeliveryInput(has_target=True, facts=_green_facts(), claim_coverage=0.9)
    )

    assert verdict.status == "GREEN"


def test_red_when_no_target() -> None:
    verdict = evaluate_delivery(DeliveryInput(has_target=False, facts=_green_facts()))

    assert verdict.status == "RED"
    assert "未定位" in verdict.disclosure


def test_red_when_all_applicable_facts_failed() -> None:
    facts = [_fact("target_file_exists", False), _fact("symbol_in_file", False)]

    verdict = evaluate_delivery(DeliveryInput(has_target=True, facts=facts))

    assert verdict.status == "RED"
    assert "适用事实全部未通过" in verdict.reasons[0]


def test_not_applicable_failures_do_not_trigger_red() -> None:
    """后端项目三项样式事实恒失败，不应把交付打成 RED。"""
    facts = [
        _fact("target_file_exists", True),
        _fact("token_defined", False, applicable=False),
        _fact("has_data_testid", False, applicable=False),
    ]

    verdict = evaluate_delivery(DeliveryInput(has_target=True, facts=facts, claim_coverage=1.0))

    assert verdict.status == "GREEN"


def test_red_when_anchors_invalid() -> None:
    """U-2：正文锚点明确无效 → RED，方案照常返回。"""
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            anchor_invalid_count=2,
        )
    )

    assert verdict.status == "RED"
    assert "2 处无效锚点" in verdict.disclosure


def test_disclosure_is_localized() -> None:
    """披露文案随 locale 切换（2026-11-06，F-209 后端双语）；默认仍逐字中文。"""
    zh = evaluate_delivery(DeliveryInput(has_target=False))
    assert zh.status == "RED"
    assert "未定位到目标符号" in zh.disclosure

    en = evaluate_delivery(DeliveryInput(has_target=False), locale="en")
    assert en.status == "RED"
    assert "Target symbol not located" in en.disclosure
    assert en.tone == "error"


def test_no_anchor_penalty_when_clear() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            anchor_invalid_count=0,
        )
    )

    assert verdict.status == "GREEN"


def test_red_when_claims_undeclared() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(has_target=True, facts=_green_facts(), claims_undeclared=True)
    )

    assert verdict.status == "RED"
    assert any("未声明" in reason for reason in verdict.reasons)


def test_yellow_when_coverage_below_threshold() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(has_target=True, facts=_green_facts(), claim_coverage=0.5)
    )

    assert verdict.status == "YELLOW"
    assert "断言覆盖率" in verdict.disclosure


def test_no_variant_count_or_recommendation_fields() -> None:
    """单套输出后的契约：输入/输出都不再承载套数与推荐语义。"""
    assert "variant_count" not in DeliveryInput.__dataclass_fields__
    assert "expected_variant_count" not in DeliveryInput.__dataclass_fields__
    assert "can_mark_c" not in DeliveryVerdict.__dataclass_fields__
    assert "can_mark_recommend" not in DeliveryVerdict.__dataclass_fields__


def test_red_beats_yellow() -> None:
    """RED 优先：缺目标且覆盖率不足时，仍必须是 RED。"""
    verdict = evaluate_delivery(
        DeliveryInput(has_target=False, facts=_green_facts(), claim_coverage=0.1)
    )

    assert verdict.status == "RED"
