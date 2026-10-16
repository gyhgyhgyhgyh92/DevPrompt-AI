"""注册表归一化测试（M-911）。

核心不变量：**永不抛异常、永不丢条目**。本项目是本地单用户工具，数据文件
由用户手工编辑也可能出错——读取失败导致配置丢失或服务起不来，都比「显示一条
问题提示」糟糕得多。

另锁定一条重要偏离：**不实现源项目的 legacy 结构转换器**（见模块 docstring），
因为核实本项目历史后不存在需要转换的旧版数据。
"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.domain.model_migration import (
    normalize_entry,
    normalize_overrides,
    normalize_registry,
)

#: 迁移前的六字段条目（本项目 settings.json 的真实形态）
_LEGACY_ENTRY: dict[str, Any] = {
    "id": "m-e94707cd",
    "label": "DeepSeek Flash",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-xxx",
    "model_id": "deepseek-flash",
}


class TestEntryBackfill:
    def test_six_field_entry_gets_defaults(self) -> None:
        entry, problems = normalize_entry(dict(_LEGACY_ENTRY))
        assert problems == []
        assert entry["capabilities"]["supports_tools"] is True
        assert entry["capabilities"]["max_context_length"] == 64000
        assert entry["param_overrides"] == {}

    def test_existing_fields_untouched(self) -> None:
        entry, _ = normalize_entry(dict(_LEGACY_ENTRY))
        for key in ("id", "label", "provider", "base_url", "api_key", "model_id"):
            assert entry[key] == _LEGACY_ENTRY[key]

    def test_is_idempotent(self) -> None:
        """归一化两次结果必须一致——否则每次读文件都会「进化」一次。"""
        once, _ = normalize_entry(dict(_LEGACY_ENTRY))
        twice, _ = normalize_entry(dict(once))
        assert once == twice


class TestNeverRaises:
    @pytest.mark.parametrize("raw", [None, 42, "文本", [], {}, [1, 2]])
    def test_non_dict_input_yields_usable_entry(self, raw: object) -> None:
        entry, problems = normalize_entry(raw)
        assert entry["capabilities"]["supports_tools"] is True
        assert entry["param_overrides"] == {}

    def test_missing_provider_falls_back_to_generic(self) -> None:
        """缺 provider 时按通用兼容档给能力，而不是拒绝读取。"""
        entry, _ = normalize_entry({"model_id": "some-model"})
        assert entry["provider"] == ""
        assert entry["capabilities"]["max_context_length"] == 128000

    def test_wrong_field_types_are_coerced(self) -> None:
        entry, _ = normalize_entry({"provider": 123, "model_id": ["a"], "api_key": {"k": 1}})
        assert entry["provider"] == ""
        assert entry["model_id"] == ""
        assert isinstance(entry["api_key"], dict), "未知类型字段原样保留，不擅自丢弃"


class TestTextCleaning:
    def test_strips_whitespace(self) -> None:
        entry, _ = normalize_entry({"provider": "  deepseek  ", "model_id": " flash "})
        assert entry["provider"] == "deepseek"
        assert entry["model_id"] == "flash"

    def test_overlong_model_id_is_truncated_with_problem(self) -> None:
        entry, problems = normalize_entry({"model_id": "x" * 500})
        assert len(entry["model_id"]) < 500
        assert any("过长" in p for p in problems)

    def test_unknown_fields_preserved(self) -> None:
        """不擅自删除用户手工加的字段——那是用户的文件。"""
        entry, _ = normalize_entry({**dict(_LEGACY_ENTRY), "my_note": "别删我"})
        assert entry["my_note"] == "别删我"


class TestOverridesCleaning:
    def test_non_dict_overrides_becomes_empty(self) -> None:
        assert normalize_overrides("deepseek", "不是字典") == {}
        assert normalize_overrides("deepseek", None) == {}

    def test_dangerous_keys_dropped(self) -> None:
        cleaned = normalize_overrides("deepseek", {"__proto__": 1, "temperature": 0.5})
        assert "__proto__" not in cleaned
        assert cleaned["temperature"] == 0.5

    def test_unsupported_params_dropped(self) -> None:
        cleaned = normalize_overrides("anthropic", {"temperature": 0.5, "max_tokens": 100})
        assert cleaned == {"max_tokens": 100, "reasoning_effort": "high"}

    def test_empty_values_dropped(self) -> None:
        cleaned = normalize_overrides("deepseek", {"temperature": None, "top_p": ""})
        assert cleaned == {}


class TestRegistryLevel:
    def test_registry_normalises_each_entry(self) -> None:
        out = normalize_registry([dict(_LEGACY_ENTRY), {"provider": "openai", "model_id": "gpt"}])
        assert len(out) == 2
        assert all("capabilities" in e for e in out)

    def test_non_list_input_yields_empty(self) -> None:
        assert normalize_registry("不是列表") == []
        assert normalize_registry(None) == []

    def test_non_dict_items_skipped(self) -> None:
        out = normalize_registry([dict(_LEGACY_ENTRY), "垃圾数据", None, 42])
        assert len(out) == 1

    def test_empty_list_stays_empty(self) -> None:
        assert normalize_registry([]) == []


class TestCapabilitiesNormalisation:
    def test_user_overrides_are_honoured(self) -> None:
        entry, _ = normalize_entry({"provider": "zhipu", "capabilities": {"supports_tools": False}})
        assert entry["capabilities"]["supports_tools"] is False
        assert entry["capabilities"]["max_context_length"] == 128000, "未覆盖字段用默认补齐"

    def test_wrong_type_capability_ignored(self) -> None:
        entry, _ = normalize_entry({"provider": "zhipu", "capabilities": {"supports_tools": "yes"}})
        assert entry["capabilities"]["supports_tools"] is True, "类型不符则回退默认"

    def test_bool_is_not_treated_as_context_length(self) -> None:
        """bool 是 int 子类——若不排除，`max_context_length: true` 会变成 1。"""
        entry, _ = normalize_entry(
            {"provider": "zhipu", "capabilities": {"max_context_length": True}}
        )
        assert entry["capabilities"]["max_context_length"] == 128000

    def test_valid_custom_context_length_kept(self) -> None:
        entry, _ = normalize_entry(
            {"provider": "acme", "capabilities": {"max_context_length": 999}}
        )
        assert entry["capabilities"]["max_context_length"] == 999


class TestNoLegacyConverter:
    """锁定一项重要偏离：本项目不实现 legacy 结构转换器。

    核实结论：settings.json 自建立以来顶层键与条目字段均未变过，不存在需要转换的
    旧版数据。照搬源项目converter.ts 会产出永不执行的死代码。此测试防止后���
    「照搬」冲动把死代码加回来。
    """

    def test_module_exposes_no_legacy_converter(self) -> None:
        from devprompt_ai.domain import model_migration

        exported = [
            n for n in dir(model_migration) if "legacy" in n.lower() or "convert" in n.lower()
        ]
        assert exported == [], f"不应存在 legacy 转换入口：{exported}"

    def test_camel_case_legacy_keys_are_not_special_cased(self) -> None:
        """camelCase 老键（baseURL 等）不特殊处理——落到未知字段原样保留。"""
        entry, _ = normalize_entry({"baseURL": "https://x", "llmParams": {"a": 1}})
        assert entry["baseURL"] == "https://x"
        assert entry["llmParams"] == {"a": 1}
        assert entry["provider"] == ""
