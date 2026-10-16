"""每模型参数的生效链路测试（M-914）。

链路：`param_overrides` →（激活时镜像进 model_service.llm_params）→ AppConfig
→ `effective_llm_params()` → `ModelSettings`。本文件锁定合并优先级与两个关键边界：

1. **模型级覆盖全局默认**（裁定 D3）；
2. **只返回 ModelSettings 原生键** —— `apply_provider_constraints` 会注入
   `force_params`（如 anthropic 的 reasoning_effort），该键不在 ModelSettings 字段内，
   放进去会被 pydantic 当 extra 收下，行为不确定（可能静默失效，也可能透传报错）。
"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.model_spec import NATIVE_PARAMETERS


def _cfg(**kwargs: Any) -> AppConfig:
    return AppConfig(_env_file=None, **kwargs)  # type: ignore[call-arg]


class TestMergePriority:
    def test_global_only(self) -> None:
        cfg = _cfg(llm_provider="deepseek", llm_temperature=0.7, llm_max_tokens=1024)
        assert cfg.effective_llm_params() == {"temperature": 0.7, "max_tokens": 1024}

    def test_model_level_overrides_global(self) -> None:
        cfg = _cfg(
            llm_provider="deepseek",
            llm_temperature=0.7,
            llm_max_tokens=1024,
            llm_params={"temperature": 0.2},
        )
        assert cfg.effective_llm_params()["temperature"] == 0.2
        assert cfg.effective_llm_params()["max_tokens"] == 1024

    def test_unset_values_absent_from_result(self) -> None:
        """未设值的键不能出现在结果里——要交给供应商用自己的默认值。"""
        assert _cfg(llm_provider="zhipu").effective_llm_params() == {}

    def test_extra_provider_has_no_constraints(self) -> None:
        cfg = _cfg(llm_provider="acme", llm_temperature=0.5)
        assert cfg.effective_llm_params() == {"temperature": 0.5}


class TestNativeOnly:
    def test_unsupported_param_dropped_for_provider(self) -> None:
        """Anthropic 不接受 temperature——剔除后才不会发出会报错的请求。"""
        cfg = _cfg(llm_provider="anthropic", llm_temperature=0.7, llm_max_tokens=1024)
        result = cfg.effective_llm_params()
        assert "temperature" not in result
        assert result["max_tokens"] == 1024

    def test_force_params_never_leak(self) -> None:
        """force_params（reasoning_effort）不属于 ModelSettings 字段，绝不能混进来。"""
        for provider in ("anthropic", "gemini", "deepseek", "openai", "zhipu"):
            cfg = _cfg(llm_provider=provider, llm_temperature=0.5)
            result = cfg.effective_llm_params()
            assert set(result) <= NATIVE_PARAMETERS, f"{provider} 泄漏了非原生键：{result}"

    def test_result_is_accepted_by_model_settings(self) -> None:
        """最终产物必须能被 ModelSettings 直接展开——否则调用时才崩就太晚了。"""
        from agents import ModelSettings

        for provider in ("anthropic", "gemini", "deepseek", "openai", "zhipu", "acme"):
            cfg = _cfg(llm_provider=provider, llm_temperature=0.5, llm_max_tokens=2048)
            ModelSettings(**cfg.effective_llm_params())

    @pytest.mark.parametrize("key", ["temperature", "max_tokens", "top_p"])
    def test_native_parameters_are_configurable(self, key: str) -> None:
        assert key in NATIVE_PARAMETERS


class TestLoadChain:
    def test_llm_params_defaults_to_empty(self) -> None:
        assert _cfg().llm_params == {}

    def test_llm_params_can_be_set_via_init(self) -> None:
        assert _cfg(llm_params={"max_tokens": 512}).llm_params["max_tokens"] == 512

    def test_mapping_registers_llm_params_key(self) -> None:
        """model_service 段的 llm_params 必须能被本地设置源读到，否则镜像不生效。"""
        from devprompt_ai.config import MODEL_KEY_MAP

        assert MODEL_KEY_MAP["llm_params"] == "llm_params"
