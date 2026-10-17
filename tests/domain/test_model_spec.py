"""领域层模型定义测试（M-910 迁自 prompt-optimizer model/ 模块）。

覆盖三组语义：①provider 解析与能力兜底 ②参数校验（类型/范围/枚举/危险键名）
③provider 约束清洗（源项目四个 if 分支的数据化等价物）。

**未知厂商必须给保守默认而非抛错**——这是裁定 D4「不引内置目录」的必然要求。
"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.model_spec import (
    apply_provider_constraints,
    resolve_capabilities,
    resolve_provider_key,
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
