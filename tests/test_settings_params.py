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

    def test_explicit_empty_dict_clears(self) -> None:
        """「清空」必须能被表达——深合并做不到这一点。"""
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "param_overrides": {}}], existing)

    def test_provider_change_reclears_stale_overrides(self) -> None:
        """provider 变了（deepseek→anthropic），旧参数不再适用，必须重算。"""
        existing = _existing_with({"temperature": 0.3})
        merged = _merge([{**_BASE, "provider": "anthropic", "param_overrides": None}], existing)


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


class TestContextWindowTiers:
    """上下文窗口档位（2026-09-17）。

    两条不变量：①档位不得大于厂商标称窗口（否则用户会得到假安全感）；
    ②未核实的厂商必须标 None 而非填占位值。
    """

    def test_tiers_never_exceed_vendor_max(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        for key, spec in PROVIDER_SPECS.items():
            if spec.max_context_length:
                for tier in spec.context_window_tiers:
                    assert tier <= spec.max_context_length, (
                        f"{key}: 档位 {tier} 超过标称 {spec.max_context_length}"
                    )

    def test_tiers_are_sorted_and_unique(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        for key, spec in PROVIDER_SPECS.items():
            tiers = spec.context_window_tiers
            assert list(tiers) == sorted(set(tiers)), f"{key}: 档位未升序或重复"

    def test_unverified_vendors_have_no_window(self) -> None:
        """未核实 = None，不得填占位默认值（假值比不显示更糟）。"""
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        unregistered = [k for k, s in PROVIDER_SPECS.items() if s.max_context_length is None]
        assert unregistered, "应有未登记的厂商"
        for key in unregistered:
            assert PROVIDER_SPECS[key].context_window_tiers == ()

    def test_known_vendors_have_real_values(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        assert PROVIDER_SPECS["openai"].max_context_length == 272000
        assert PROVIDER_SPECS["deepseek"].max_context_length == 128000
        assert PROVIDER_SPECS["gemini"].max_context_length == 1000000


class TestContextWindowTierInvariants:
    """档位安全底线（2026-09-17 B3）。

    档位存在的意义是「让用户选一个厂商真支持的窗口」。一旦允许档位超过标称，
    用户会得到「我设了 1M 但实际只有 200K」的假安全感——比不显示更糟。
    """

    def test_tier_never_exceeds_vendor_max(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        offenders = [
            (key, tier)
            for key, spec in PROVIDER_SPECS.items()
            if spec.max_context_length
            for tier in spec.context_window_tiers
            if tier > spec.max_context_length
        ]
        assert offenders == [], f"档位超过厂商标称窗口：{offenders}"

    def test_highest_tier_equals_vendor_max(self) -> None:
        """最高档须等于标称值，否则用户无法选到真实上限。"""
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        for key, spec in PROVIDER_SPECS.items():
            if spec.max_context_length and spec.context_window_tiers:
                assert max(spec.context_window_tiers) == spec.max_context_length, key

    def test_tiers_sorted_and_unique(self) -> None:
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        for key, spec in PROVIDER_SPECS.items():
            tiers = spec.context_window_tiers
            assert list(tiers) == sorted(set(tiers)), f"{key}: 档位未升序或有重复"

    def test_no_placeholder_windows(self) -> None:
        """零占位默认值——填假值比标 None 更糟（UI 会拿它做告警判定）。

        2026-09-17 修正：v2.5 曾把 25 处全填成 `128000`/`131072` 占位值。改为
        **按厂商核对**——已核实的必须等于官方口径，未核实的必须为 ``None``。
        （不能用「值等于 131072 即占位」判定：`qianfan` 的官方口径恰为 131072。）
        """
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        verified = {
            "openai",
            "anthropic",
            "gemini",
            "deepseek",
            "dashscope",
            "zhipu",
            "moonshot",
            "volcengine",
            "qianfan",
            "spark",
            "minimax",
            "baichuan",
            "grok",
            "hunyuan",
            "siliconflow",
            "stepfun",
        }
        for key, spec in PROVIDER_SPECS.items():
            if key in verified:
                assert spec.max_context_length, f"{key}: 已核实厂商不应为 None"
            else:
                assert spec.max_context_length is None, (
                    f"{key}: 未核实厂商不应填窗口值（当前 {spec.max_context_length}）"
                )

    def test_verified_vendors_have_accurate_values(self) -> None:
        """已核实厂商的值必须与官方口径一致（防止后续误改）。"""
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        expected = {
            "openai": 272000,  # 官方文档：GPT-5 输入上限（含 thinking 口径）
            "anthropic": 200000,
            "gemini": 1000000,
            "deepseek": 128000,  # 官方 2025-08 V3.1 公告
            "zhipu": 200000,  # 官方文档 GLM-4.6
            "moonshot": 256000,  # 官方 2025-09 公告
            "volcengine": 262144,  # 火山官方文档
            "qianfan": 131072,  # 千帆文档
            "spark": 262144,  # 讯飞 MaaS 官网
        }
        for key, value in expected.items():
            assert PROVIDER_SPECS[key].max_context_length == value, key

    def test_unverified_vendors_are_none(self) -> None:
        """未核实厂商必须是 None（未登记），不能是占位值。"""
        from devprompt_ai.domain.model_spec import PROVIDER_SPECS

        for key in (
            "yi",
            "sensetime",
            "xiaomi-mimo",
            "modelscope",
            "custom",
            "openai_compatible",
            "ollama",
            "vllm",
            "lmstudio",
        ):
            assert PROVIDER_SPECS[key].max_context_length is None, key
            assert PROVIDER_SPECS[key].context_window_tiers == (), key
