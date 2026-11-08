"""三层预算测试：内存分档、窗口预留、块级配额。"""

from __future__ import annotations

from devprompt_ai.domain.context.budget import (
    fit_blocks,
    request_budget,
    turn_token_budget,
)


def test_turn_budget_drops_with_memory_pressure() -> None:
    assert turn_token_budget(0.5) == 50_000
    assert turn_token_budget(0.75) == 25_000
    assert turn_token_budget(0.9) == 0, "内存危急时禁用本轮预算（不截断）"


def test_request_budget_reserves_output_and_margin() -> None:
    budget = request_budget(window=1_000_000, max_output=64_000)

    assert budget.output_reserve == 64_000
    assert budget.safety_margin == 16_384, "边际取 5%~10% 的较大者且封顶 16K"
    assert budget.input_budget == 1_000_000 - 64_000 - 16_384


def test_request_budget_caps_output_at_half_window() -> None:
    budget = request_budget(window=100_000, max_output=256_000)

    assert budget.output_reserve == 50_000
    assert budget.input_budget > 0


def test_ratio_and_fit() -> None:
    budget = request_budget(window=100_000, max_output=10_000)

    assert budget.fits(0) is True
    assert budget.fits(budget.input_budget + 1) is False
    assert 0.0 <= budget.ratio(1_000) <= 1.0


def test_fit_blocks_truncates_only_known_quota() -> None:
    fitted = fit_blocks(
        {"project_memory": "x" * 4000, "unknown": "y" * 9000},
        {"project_memory": 100},
    )

    assert len(fitted["project_memory"]) == 100
    assert fitted["project_memory"].endswith("…")
    assert len(fitted["unknown"]) == 9000
