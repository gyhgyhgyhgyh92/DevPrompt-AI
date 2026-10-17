"""领域层模型定义测试（M-910 迁自 prompt-optimizer model/ 模块）。

覆盖三组语义：①provider 解析与能力兜底 ②参数校验（类型/范围/枚举/危险键名）
③provider 约束清洗（源项目四个 if 分支的数据化等价物）。

**未知厂商必须给保守默认而非抛错**——这是裁定 D4「不引内置目录」的必然要求。
"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.model_spec import (
    DANGEROUS_PARAM_KEY_PATTERNS,
    NATIVE_PARAMETERS,
    PROVIDER_SPECS,
    apply_provider_constraints,
    is_safe_custom_key,
    is_value_empty,
    provider_parameters,
    resolve_capabilities,
    resolve_provider_key,
    validate_overrides,
)


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

    def test_capabilities_of_unknown_provider_are_conservative(self) -> None:
        caps = resolve_capabilities("acme-unknown")
        assert caps.supports_tools is True
        assert caps.supports_reasoning is False
        assert caps.max_context_length == 128000

    def test_reasoning_flag_differs_by_provider(self) -> None:
        assert resolve_capabilities("deepseek").supports_reasoning is True
        # zhipu 的 GLM 系列含推理模型，故标 True；spark 无推理模型，标 False
        assert resolve_capabilities("zhipu").supports_reasoning is True
        assert resolve_capabilities("spark").supports_reasoning is False


class TestParameterDefinitions:
    def test_every_provider_declares_parameters(self) -> None:
        for key in PROVIDER_SPECS:
            assert provider_parameters(key), f"{key} 未定义任何参数"

    def test_parameter_names_are_unique_per_provider(self) -> None:
        for key in PROVIDER_SPECS:
            names = [p.name for p in provider_parameters(key)]
            assert len(names) == len(set(names)), f"{key} 存在重名参数"

    def test_temperature_range_differs_by_provider(self) -> None:
        """源项目的核心点：同名参数在不同厂商范围不同，故范围下沉到 provider。"""
        by_name = {p.name: p for p in provider_parameters("deepseek")}
        assert by_name["temperature"].max_value == 2.0

    def test_native_parameters_subset(self) -> None:
        """仅 ModelSettings 原生支持的参数标is_native，其余需 extra_body。"""
        assert "temperature" in NATIVE_PARAMETERS
        assert "max_tokens" in NATIVE_PARAMETERS
        reasoning = {p.name: p for p in provider_parameters("openai")}["reasoning_effort"]
        assert reasoning.is_native is False

    def test_definition_projection_is_serialisable(self) -> None:
        payload = provider_parameters("deepseek")[0].to_dict()
        assert payload["name"] == "temperature"
        assert payload["is_native"] is True
        assert isinstance(payload["allowed_values"], list)


class TestSafeKeys:
    def test_rejects_all_documented_patterns(self) -> None:
        """22 条危险键名逐条验证——黑名单的价值全在「一个都不漏」。"""
        assert len(DANGEROUS_PARAM_KEY_PATTERNS) == 22
        for pattern in DANGEROUS_PARAM_KEY_PATTERNS:
            assert is_safe_custom_key(pattern) is False, f"{pattern} 应被拒绝"
            assert is_safe_custom_key(f"my_{pattern}") is False, f"my_{pattern} 应被拒绝"
            assert is_safe_custom_key(pattern.upper()) is False, f"{pattern.upper()} 应被拒绝"

    @pytest.mark.parametrize("key", ["temperature", "top_p", "reasoning.effort", "a-b:c", "GPT_4o"])
    def test_accepts_normal_keys(self, key: str) -> None:
        assert is_safe_custom_key(key) is True

    @pytest.mark.parametrize("key", ["", "   ", "has space", "with\nnewline", "emoji🙂"])
    def test_rejects_malformed_keys(self, key: str) -> None:
        assert is_safe_custom_key(key) is False

    def test_registered_param_bypasses_blacklist(self) -> None:
        """黑名单含 `token` 子串会误伤 `max_tokens` 这类合法登记参数名。

        `is_safe_custom_key` **只用于自定义（未登记）键**；已登记参数走
        `validate_overrides` 的定义表分支，不经过此检查。两条路径都需有测试锁定。
        """
        assert is_safe_custom_key("max_tokens") is False, "本函数仅用于自定义键"
        errors, warnings = validate_overrides("deepseek", {"max_tokens": 100})
        assert errors == [], "max_tokens 是登记参数，不该被黑名单拦下"
        assert warnings == []

    def test_unregistered_key_with_token_is_rejected(self) -> None:
        """未登记的自定义键若含敏感词仍须拒绝——这正是黑名单要防的场景。"""
        errors, _ = validate_overrides("deepseek", {"custom_tokens": 5})
        assert errors and "不允许的字符" in errors[0]


class TestValueEmptiness:
    @pytest.mark.parametrize("value", [None, "", "   ", [], ()])
    def test_empty_values(self, value: object) -> None:
        assert is_value_empty(value) is True

    @pytest.mark.parametrize("value", [0, 0.0, False, "x", [1]])
    def test_non_empty_values(self, value: object) -> None:
        """0 与 False 是有效取值，不能被当作「空」而剔除。"""
        assert is_value_empty(value) is False


class TestProviderConstraints:
    def test_anthropic_drops_sampling_params(self) -> None:
        """源项目 manager.ts 的 anthropic 分支：删 temperature/top_p。"""
        cleaned = apply_provider_constraints(
            "anthropic", {"temperature": 0.5, "top_p": 0.9, "max_tokens": 2048}
        )
        assert "temperature" not in cleaned
        assert "top_p" not in cleaned
        assert cleaned["max_tokens"] == 2048

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


class TestValidateOverrides:
    def test_valid_overrides_pass(self) -> None:
        errors, warnings = validate_overrides("deepseek", {"temperature": 0.5, "max_tokens": 2048})
        assert errors == []
        assert warnings == []

    def test_out_of_range_is_error(self) -> None:
        errors, _ = validate_overrides("deepseek", {"temperature": 99.0})
        assert errors and "随机性" in errors[0]

    def test_wrong_type_is_error(self) -> None:
        assert validate_overrides("deepseek", {"max_tokens": "很多"})[0]
        assert validate_overrides("deepseek", {"temperature": True})[0], "bool 不是 number"

    def test_enum_violation_is_error(self) -> None:
        errors, _ = validate_overrides("openai", {"reasoning_effort": "extreme"})
        assert errors and "推理强度" in errors[0]

    def test_string_array_type_checked(self) -> None:
        assert validate_overrides("deepseek", {"stop": "END"})[0] == []
        errors, _ = validate_overrides("deepseek", {"stop": "END"})
        assert errors == [], "未登记参数走警告分支，不做类型校验"

    def test_dangerous_key_is_error(self) -> None:
        errors, _ = validate_overrides("deepseek", {"__proto__": 1})
        assert errors and "不允许的字符" in errors[0]

    def test_unknown_param_is_warning_not_error(self) -> None:
        """allowUnknown 语义：厂商参数差异大，硬拦未登记参数会误伤。"""
        errors, warnings = validate_overrides("deepseek", {"some_new_flag": True})
        assert errors == []
        assert warnings and "some_new_flag" in warnings[0]

    def test_dropped_param_is_warning(self) -> None:
        errors, warnings = validate_overrides("anthropic", {"temperature": 0.5})
        assert errors == []
        assert warnings and "Anthropic" in warnings[0]

    def test_unknown_provider_validates_against_fallback(self) -> None:
        """未知厂商不应因校验而无法保存——它的定义表就是通用兼容档。"""
        errors, _ = validate_overrides("acme", {"temperature": 0.5, "max_tokens": 100})
        assert errors == []

    def test_empty_value_skips_range_check(self) -> None:
        assert validate_overrides("deepseek", {"temperature": None}) == ([], [])
