"""service 层模型条目合并与校验测试（M-913）。

锁定的核心语义（对齐源项目 `manager.ts:968-972`）：`param_overrides` 是**整体替换**
而非深合并——否则用户删掉的参数会被「礼貌地」保留回来，这正是该处注释指出的问题。
三态必须分明：显式 dict=替换、None=沿用同 id 旧值、显式 {}=清空。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.service import ForgeService

_BASE: dict[str, Any] = {
    "id": "m-1",
    "label": "DeepSeek",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "model_id": "deepseek-flash",
}


def _merge(incoming: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return ForgeService._merge_registry_entries(incoming, existing)


def _existing_with(overrides: dict[str, Any]) -> list[dict[str, Any]]:
    return _merge([{**_BASE, "param_overrides": overrides}], [])


class TestOverridesReplaceSemantics:
    def test_explicit_dict_replaces_wholesale(self) -> None:
        """整体替换：旧值不该残留。"""
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "param_overrides": {"max_tokens": 99}}], existing)
        assert merged[0]["param_overrides"] == {"max_tokens": 99}
        assert "temperature" not in merged[0]["param_overrides"]

    def test_none_inherits_existing(self) -> None:
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "param_overrides": None}], existing)
        assert merged[0]["param_overrides"] == {"temperature": 0.3}

    def test_explicit_empty_dict_clears(self) -> None:
        """「清空」必须能被表达——深合并做不到这一点。"""
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "param_overrides": {}}], existing)
        assert merged[0]["param_overrides"] == {}

    def test_absent_key_inherits_existing(self) -> None:
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE}], existing)
        assert merged[0]["param_overrides"] == {"temperature": 0.3}

    def test_new_entry_gets_empty_overrides(self) -> None:
        merged = _merge([_BASE], [])
        assert merged[0]["param_overrides"] == {}

    def test_provider_change_reclears_stale_overrides(self) -> None:
        """provider 变了（deepseek→anthropic），旧参数不再适用，必须重算。"""
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "provider": "anthropic", "param_overrides": None}], existing)
        assert "temperature" not in merged[0]["param_overrides"]


class TestEntryValidation:
    def test_valid_entry_passes(self) -> None:
        entry = _merge([{**_BASE, "param_overrides": {"temperature": 0.5}}], [])[0]
        assert ForgeService._validate_registry_entries([entry]) == []

    def test_missing_model_id_rejected(self) -> None:
        assert ForgeService._validate_registry_entries(
            [{"id": "m-1", "label": "x", "model_id": "", "base_url": "https://x"}]
        )

    def test_missing_base_url_rejected(self) -> None:
        assert ForgeService._validate_registry_entries(
            [{"id": "m-1", "label": "x", "model_id": "m", "base_url": ""}]
        )

    def test_out_of_range_param_rejected(self) -> None:
        entry = _merge([{**_BASE, "param_overrides": {"temperature": 99}}], [])[0]
        problems = ForgeService._validate_registry_entries([entry])
        assert problems and "随机性" in problems[0]

    def test_dangerous_param_key_rejected(self) -> None:
        entry = {**_BASE, "param_overrides": {"__proto__": 1}}
        problems = ForgeService._validate_registry_entries([entry])
        assert problems and "不允许的字符" in problems[0]

    def test_error_message_prefixed_with_entry_label(self) -> None:
        """错误必须指明是哪个条目出的问题，否则用户无从下手。"""
        entry, _ = (
            _merge([{**_BASE, "label": "我的模型", "param_overrides": {"temperature": 99}}], [])[0],
            None,
        )
        problems = ForgeService._validate_registry_entries([entry])
        assert problems[0].startswith("我的模型：")

    def test_unknown_param_not_blocking(self) -> None:
        """未登记参数只告警不阻断——厂商参数差异大，硬拦会误伤。"""
        entry = _merge([{**_BASE, "param_overrides": {"vendor_flag": True}}], [])[0]
        assert ForgeService._validate_registry_entries([entry]) == []


class TestLegacyBehaviourPreserved:
    def test_api_key_inherits_on_empty(self) -> None:
        """既有语义不得因迁移而破坏。"""
        existing = _merge([{**_BASE, "api_key": "sk-old"}], [])
        merged = _merge([{**_BASE, "api_key": ""}], existing)
        assert merged[0]["api_key"] == "sk-old"

    def test_id_generated_when_absent(self) -> None:
        merged = _merge([{k: v for k, v in _BASE.items() if k != "id"}], [])
        assert merged[0]["id"].startswith("m-")

    def test_label_derived_when_blank(self) -> None:
        merged = _merge([{**_BASE, "label": ""}], [])
        assert merged[0]["label"] == "deepseek · deepseek-flash"


class TestModelSpecsProjection:
    def test_projection_covers_all_providers(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS, model_specs_projection

        projection = model_specs_projection()
        assert set(projection) == set(PROVIDER_SPECS)

    def test_projection_entries_are_serialisable(self) -> None:
        from devprompt_ai.domain.model_spec import model_specs_projection

        payload = model_specs_projection()["deepseek"][0]
        assert {"name", "type", "label", "min_value", "max_value", "is_native"} <= set(payload)
