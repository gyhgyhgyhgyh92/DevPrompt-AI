"""交付证据门测试：三态优先级、不适用项不参与、RED 不阻断交付。"""

from __future__ import annotations

from typing import cast

from devprompt_ai.domain.delivery.gate import DeliveryInput, evaluate_delivery
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
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=0.9,
            variant_count=3,
            recommend_marked=True,
        )
    )

    assert verdict.status == "GREEN"
    assert verdict.can_mark_c is True
    assert verdict.can_mark_recommend is True
    assert verdict.disclosure == ""


def test_red_when_no_target() -> None:
    verdict = evaluate_delivery(DeliveryInput(has_target=False, facts=_green_facts()))

    assert verdict.status == "RED"
    assert verdict.can_mark_c is False
    assert verdict.can_mark_recommend is False
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

    verdict = evaluate_delivery(
        DeliveryInput(has_target=True, facts=facts, claim_coverage=1.0, variant_count=2)
    )

    assert verdict.status == "GREEN"


def test_red_when_claims_undeclared() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claims_undeclared=True,
            variant_count=3,
        )
    )

    assert verdict.status == "RED"
    assert any("未声明" in reason for reason in verdict.reasons)


def test_yellow_when_coverage_below_threshold() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=0.5,
            variant_count=3,
            recommend_marked=True,
        )
    )

    assert verdict.status == "YELLOW"
    assert verdict.can_mark_c is True
    assert verdict.can_mark_recommend is False
    assert "断言覆盖率" in verdict.disclosure


def test_yellow_when_single_variant() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            variant_count=1,
        )
    )

    assert verdict.status == "YELLOW"
    assert "仅一套方案" in verdict.disclosure


def test_yellow_when_fewer_variants_than_expected() -> None:
    """U-7：请求 3 套实际 2 套 → YELLOW 披露但不阻断，仍可标 C。"""
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            variant_count=2,
            expected_variant_count=3,
        )
    )

    assert verdict.status == "YELLOW"
    assert "本次仅 2 套" in verdict.disclosure
    assert verdict.can_mark_c is True


def test_no_shortfall_disclosure_when_count_matches() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            variant_count=3,
            expected_variant_count=3,
        )
    )

    assert verdict.status == "GREEN"
    assert "本次仅" not in verdict.disclosure


def test_yellow_when_recommendation_confidence_insufficient() -> None:
    verdict = evaluate_delivery(
        DeliveryInput(
            has_target=True,
            facts=_green_facts(),
            claim_coverage=1.0,
            variant_count=3,
            recommend_marked=False,
            recommend_reason="三套适配度接近，建议人工选择",
        )
    )

    assert verdict.status == "YELLOW"
    assert "三套适配度接近" in verdict.disclosure


def test_red_beats_yellow() -> None:
    """RED 优先：即使是单套方案，缺目标也必须是 RED。"""
    verdict = evaluate_delivery(
        DeliveryInput(has_target=False, facts=_green_facts(), variant_count=1)
    )

    assert verdict.status == "RED"
    assert verdict.can_mark_recommend is False
