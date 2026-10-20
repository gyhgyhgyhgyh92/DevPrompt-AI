"""领域层模型定义测试（M-910 迁自 prompt-optimizer model/ 模块）。

覆盖三组语义：①provider 解析与能力兜底 ②参数校验（类型/范围/枚举/危险键名）
③provider 约束清洗（源项目四个 if 分支的数据化等价物）。

**未知厂商必须给保守默认而非抛错**——这是裁定 D4「不引内置目录」的必然要求。
"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.model_spec import (
    apply_provider_constraints,
    context_window_alert,
    max_context_length_of,
    model_meta_of,
    providers_projection,
    resolve_capabilities,
    resolve_provider_key,
    window_tiers,
)


class TestWindowTiers:
    def test_ladder_from_128k_up(self) -> None:
        assert window_tiers(1_048_576) == (131_072, 262_144, 524_288, 1_048_576)

    def test_window_below_floor_yields_nominal_only(self) -> None:
        assert window_tiers(64_000) == (64_000,)

    def test_unknown_window_yields_nothing(self) -> None:
        assert window_tiers(None) == ()

    def test_vendor_tiers_are_unioned_not_replaced(self) -> None:
        assert window_tiers(200_000, (100_000, 999_999)) == (100_000, 131_072, 200_000)


class TestProviderResolution:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("deepseek", "deepseek"),
            ("DeepSeek", "deepseek"),
            ("  openai  ", "openai"),
            ("claude", "anthropic"),
            ("anthropic", "anthropic"),
            ("google", "gemini"),
            ("xai", "grok"),
            ("glm", "zhipu"),
            ("openai-compatible", "openai_compatible"),
        ],
    )
    def test_known_aliases(self, raw: str, expected: str) -> None:
        assert resolve_provider_key(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "不存在的厂商", "acme"])
    def test_unknown_falls_back_without_raising(self, raw: str) -> None:
        """未知厂商走通用兼容档——用户自建端点是常态，不能因此报错。"""
        assert resolve_provider_key(raw) == "openai_compatible"

    def test_reasoning_flag_differs_by_provider(self) -> None:
        assert resolve_capabilities("deepseek").supports_reasoning is True
        # zhipu 的 GLM 系列含推理模型，故标 True；spark 无推理模型，标 False
        assert resolve_capabilities("zhipu").supports_reasoning is True
        assert resolve_capabilities("spark").supports_reasoning is False

    def test_anthropic_forces_effort(self) -> None:
        cleaned = apply_provider_constraints("claude", {"reasoning_effort": "low"})
        assert cleaned["reasoning_effort"] == "high"

    def test_gemini_drops_penalties(self) -> None:
        cleaned = apply_provider_constraints(
            "gemini", {"frequency_penalty": 0.3, "presence_penalty": 0.3, "max_tokens": 100}
        )
        assert "frequency_penalty" not in cleaned
        assert "presence_penalty" not in cleaned
        assert cleaned["max_tokens"] == 100

    def test_empty_values_are_stripped_before_send(self) -> None:
        """空串下发会让部分供应商报参数错误。"""
        cleaned = apply_provider_constraints(
            "deepseek", {"temperature": None, "top_p": "", "max_tokens": 0}
        )
        assert cleaned == {"max_tokens": 0}, "max_tokens=0 是有效值，不该被当成空剔除"

    def test_deepseek_keeps_sampling_params(self) -> None:
        cleaned = apply_provider_constraints("deepseek", {"temperature": 0.7})
        assert cleaned["temperature"] == 0.7


class TestContextWindowAlert:
    """F-921：按**比例**告警而非绝对值（换模型/换档位不用改阈值）。"""

    def test_unknown_window_never_alerts(self) -> None:
        assert context_window_alert(10_000_000, None) is False
        assert context_window_alert(10_000_000, 0) is False
        assert context_window_alert(10_000_000, -1) is False

    def test_at_threshold_does_not_alert(self) -> None:
        """恰好 90% 不告警——阈值是「超过」而非「达到」。"""
        assert context_window_alert(90, 100) is False

    def test_above_threshold_alerts(self) -> None:
        assert context_window_alert(91, 100) is True

    def test_absolute_overrun_below_ratio_does_not_alert(self) -> None:
        """旧口径的反例：估算已超窗口但未到 90% 时不告警。"""
        assert context_window_alert(95, 100) is True
        assert context_window_alert(85, 100) is False

    def test_ratio_is_window_independent(self) -> None:
        """同一比例跨档位一致：1M 档的 95 万 token 与 300K 档的 28.5 万同样告警。"""
        assert context_window_alert(950_000, 1_048_576) is True
        assert context_window_alert(285_000, 300_000) is True


class TestModelLevelMetadata:
    """2026-10-17 下沉：模型级优先，未登记回落厂商级（零回退）。"""

    def test_known_model_uses_model_level_window(self) -> None:
        assert max_context_length_of("deepseek", "deepseek-v4-pro") == 1_048_576
        assert max_context_length_of("deepseek", "deepseek-flash") == 1_048_576

    def test_model_id_is_case_insensitive(self) -> None:
        assert max_context_length_of("deepseek", "DeepSeek-V4-Pro") == 1_048_576

    def test_unregistered_model_falls_back_to_provider_level(self) -> None:
        """未登记模型仍用厂商级值——下沉对存量行为零影响。"""
        assert max_context_length_of("deepseek", "deepseek-v4-flash") == 1_048_576
        assert max_context_length_of("deepseek", "") == 1_048_576

    def test_blank_model_id_never_matches(self) -> None:
        assert model_meta_of("deepseek", "   ") is None
        assert model_meta_of("deepseek", "") is None

    def test_unknown_provider_has_no_model_entry(self) -> None:
        assert model_meta_of("no-such-vendor", "deepseek-v4-pro") is None

    def test_alias_provider_resolves_to_same_model(self) -> None:
        assert model_meta_of("DeepSeek", "deepseek-flash") is not None

    def test_capabilities_take_model_level_values(self) -> None:
        caps = resolve_capabilities("deepseek", "deepseek-v4-pro")
        assert caps.max_context_length == 1_048_576
        assert caps.supports_reasoning is True

    def test_reasoning_efforts_are_per_model_and_doc_backed(self) -> None:
        """DeepSeek 官方《Thinking Mode》：low/high/max，默认 high（2026-10-18 核实）。

        档位必须按模型粒度独立——不同厂商/模型不可共用一份清单。
        """
        flash = model_meta_of("deepseek", "deepseek-flash")
        pro = model_meta_of("deepseek", "deepseek-v4-pro")
        assert flash is not None and pro is not None
        assert flash.reasoning_efforts == ("low", "high", "max")
        assert pro.reasoning_efforts == ("low", "high", "max")
        assert flash.default_effort == "high"
        # 未登记模型没有档位：不编占位值，UI 该段整段不渲染
        assert model_meta_of("openai", "gpt-x") is None

    def test_projection_exposes_efforts_and_default(self) -> None:
        """`providers` 段必须把模型级强度档位下发，否则前端无从按模型配置。"""
        deepseek = next(p for p in providers_projection() if p["id"] == "deepseek")
        flash = next(m for m in deepseek["models"] if m["model_id"] == "deepseek-flash")
        assert flash["reasoning_efforts"] == ["low", "high", "max"]
        assert flash["default_effort"] == "high"

    def test_tiers_never_exceed_model_window(self) -> None:
        """F-921 不变量：档位恒 ≤ 标称窗口（防「选 1M 实际 200K」）。"""
        for entry in providers_projection():
            for tier in entry["context_window_tiers"]:
                limit = entry["max_context_length"]
                assert limit is None or tier <= limit
            for model in entry["models"]:
                assert model["model_id"]
                for tier in model["context_window_tiers"]:
                    model_limit = model["max_context_length"]
                    assert model_limit is None or tier <= model_limit
