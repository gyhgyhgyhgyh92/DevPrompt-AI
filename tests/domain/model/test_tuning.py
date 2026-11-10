"""运行时参数归一的纯函数测试（2026-11-10）。"""

from __future__ import annotations

from devprompt_ai.domain.model.tuning import (
    anthropic_thinking,
    gemini_thinking_budget,
    resolve_effort,
)


class TestResolveEffort:
    def test_empty_effort_resolves_to_none_when_model_advertises_it(self) -> None:
        assert resolve_effort("", ("none", "low", "high")) == "none"

    def test_empty_effort_stays_unset_when_none_not_advertised(self) -> None:
        assert resolve_effort("", ("low", "high")) is None

    def test_explicit_effort_is_kept(self) -> None:
        assert resolve_effort("high", ("low", "high")) == "high"

    def test_explicit_effort_is_case_insensitive(self) -> None:
        assert resolve_effort(" HIGH ", ("low", "high")) == "high"

    def test_unsupported_effort_is_ignored(self) -> None:
        assert resolve_effort("medium", ("low", "high")) is None

    def test_unknown_capability_keeps_explicit_value(self) -> None:
        """动态目录可能先于静态表提供档位：能力位为空时不丢弃显式值。"""
        assert resolve_effort("medium", ()) == "medium"


class TestAnthropicThinking:
    def test_none_disables_thinking(self) -> None:
        assert anthropic_thinking("none", 8_192) == {"type": "disabled"}

    def test_high_maps_to_budget(self) -> None:
        result = anthropic_thinking("high", 32_768)
        assert result == {"type": "enabled", "budget_tokens": 16_384}

    def test_budget_is_capped_below_max_tokens(self) -> None:
        result = anthropic_thinking("high", 8_192)
        assert result == {"type": "enabled", "budget_tokens": 7_168}

    def test_small_max_tokens_degrades_to_disabled(self) -> None:
        assert anthropic_thinking("high", 1_024) == {"type": "disabled"}
        assert anthropic_thinking("high", 2_048) == {"type": "disabled"}

    def test_empty_effort_does_not_set_thinking(self) -> None:
        assert anthropic_thinking("", 8_192) is None


class TestGeminiThinking:
    def test_none_is_zero(self) -> None:
        assert gemini_thinking_budget("none") == 0

    def test_high_maps_to_budget(self) -> None:
        assert gemini_thinking_budget("high") == 8_192

    def test_unknown_is_none(self) -> None:
        assert gemini_thinking_budget("") is None
        assert gemini_thinking_budget("ultra") is None
