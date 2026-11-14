"""通用域结构化校验 + 交付门结构化分支测试（2026-11-14 领域包）。"""

from __future__ import annotations

from devprompt_ai.domain.delivery import DeliveryInput, evaluate_delivery
from devprompt_ai.domain.delivery.structural import check_structural

_BODY = (
    "## 一、目标与背景\n写周报。\n"
    "## 二、任务拆解\n分三步。\n"
    "## 三、规范与约束\nMarkdown。\n"
    "## 四、交付标准\n可直接粘贴。"
)


def _input(body: str, changes: list[str]) -> DeliveryInput:
    return DeliveryInput(
        has_target=False,
        structural=check_structural(body, changes),
    )


def test_structural_pass_yields_green() -> None:
    verdict = evaluate_delivery(_input(_BODY, ["周报正文"]))
    assert verdict.status == "GREEN"
    assert verdict.disclosure == ""
    assert verdict.tone == "ok"


def test_missing_sections_yields_red() -> None:
    verdict = evaluate_delivery(_input(_BODY.replace("## 三、规范与约束\n", ""), ["清单"]))
    assert verdict.status == "RED"
    assert any("四段式" in reason for reason in verdict.reasons)


def test_empty_changes_yields_red() -> None:
    verdict = evaluate_delivery(_input(_BODY, []))
    assert verdict.status == "RED"
    assert any("交付物清单" in reason for reason in verdict.reasons)


def test_placeholder_yields_red() -> None:
    verdict = evaluate_delivery(_input(_BODY + "\nTODO: 数据待补充", ["清单"]))
    assert verdict.status == "RED"
    assert any("占位符" in reason for reason in verdict.reasons)


def test_inferred_marker_is_not_placeholder() -> None:
    body = _BODY + "\n范围按本周（推断）。"
    verdict = evaluate_delivery(_input(body, ["清单"]))
    assert verdict.status == "GREEN"


def test_code_branch_ignores_structural() -> None:
    # code 域（structural=None）不携带结构化结果 -> 走原分支：无 target 即 RED
    verdict = evaluate_delivery(DeliveryInput(has_target=False))
    assert verdict.status == "RED"
    assert any("目标" in reason for reason in verdict.reasons)
