"""token 用量聚合器测试（2026-11-10）。"""

from __future__ import annotations

from devprompt_ai.common.cost import (
    add_llm_tokens,
    add_llm_usage,
    take_llm_tokens,
    take_llm_usage,
)


def test_usage_aggregates_all_fields() -> None:
    add_llm_usage(100, 60, 40, 10)
    add_llm_usage(50, 30, 20, 5)

    usage = take_llm_usage()

    assert usage.total == 150
    assert usage.prompt == 90
    assert usage.completion == 60
    assert usage.cached == 15


def test_take_clears_accumulator() -> None:
    add_llm_usage(100, 60, 40)
    take_llm_usage()

    assert take_llm_usage().total == 0


def test_negative_values_are_clamped() -> None:
    add_llm_usage(-10, -5, -3, -1)

    usage = take_llm_usage()

    assert usage.total == 0
    assert usage.prompt == 0
    assert usage.completion == 0
    assert usage.cached == 0


def test_cached_none_does_not_override_previous() -> None:
    add_llm_usage(100, 60, 40, None)
    add_llm_usage(50, 30, 20, None)

    usage = take_llm_usage()

    assert usage.cached is None, "供应商从未返回缓存字段时保持 None，不虚报 0"


def test_total_only_compatibility_wrapper() -> None:
    add_llm_tokens(42)
    assert take_llm_tokens() == 42
    assert take_llm_tokens() == 0
