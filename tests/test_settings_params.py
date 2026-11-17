"""service 层供应商/条目合并与校验测试（M-913；2026-10-18 供应商中心化重构）。

锁定的核心语义：
1. **凭据只存供应商一份**——条目经 `provider_id` 引用，端点与密钥由供应商解析后展平；
2. **整表替换不做深合并**——否则用户删掉的参数会被「礼貌地」保留回来；
3. 供应商为**权威列表**：未出现的一律删除（级联），刚配好零条目的记录保留。
"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.domain.errors import ConfigurationError
from devprompt_ai.service import ForgeService

_PROVIDER: dict[str, Any] = {
    "id": "p-1",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-supplier-1234567890",
}

_BASE: dict[str, Any] = {
    "id": "m-1",
    "provider_id": "p-1",
    "model_id": "deepseek-flash",
}


def _merge(
    incoming: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    providers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return ForgeService._merge_registry_entries(
        incoming, existing, providers if providers is not None else [dict(_PROVIDER)]
    )


class TestEntryValidation:
    def test_valid_entry_passes(self) -> None:
        entry = _merge([dict(_BASE)], [])[0]
        assert ForgeService._validate_registry_entries([entry]) == []

    def test_missing_model_id_rejected(self) -> None:
        assert ForgeService._validate_registry_entries(
            [{"id": "m-1", "model_id": "", "base_url": "https://x"}]
        )

    def test_missing_base_url_rejected(self) -> None:
        assert ForgeService._validate_registry_entries(
            [{"id": "m-1", "model_id": "m", "base_url": ""}]
        )

    def test_unknown_param_not_blocking(self) -> None:
        """未登记字段只透传不阻断——厂商参数差异大，硬拦会误伤。"""
        entry = _merge([{**_BASE, "vendor_flag": True}], [])[0]
        assert ForgeService._validate_registry_entries([entry]) == []

    def test_duplicate_model_under_same_provider_rejected(self) -> None:
        """同一供应商下同一模型重复出现 = 供应商 id 撞名的副产物，必须整单拒绝。"""
        entry = _merge([dict(_BASE)], [])[0]
        problems = ForgeService._validate_registry_entries([entry, dict(entry)])
        assert any("重复" in p for p in problems)


class TestEntryMerging:
    def test_entry_resolves_endpoint_from_provider(self) -> None:
        """条目不再自带端点与密钥——全部从 `provider_id` 指向的供应商解析后展平。"""
        merged = _merge([dict(_BASE)], [])[0]
        assert merged["provider"] == "deepseek"
        assert merged["base_url"] == "https://api.deepseek.com/v1"
        assert merged["api_key"] == "sk-supplier-1234567890"

    def test_entry_pointing_unknown_provider_is_skipped(self) -> None:
        """指向不存在供应商的条目直接跳过（级联删除的兜底）。"""
        assert _merge([{**_BASE, "provider_id": "p-nope"}], []) == []

    def test_id_generated_when_absent(self) -> None:
        merged = _merge([{k: v for k, v in _BASE.items() if k != "id"}], [])
        assert merged[0]["id"].startswith("m-")

    def test_dropped_label_is_not_carried_over(self) -> None:
        """显示名称已下线：请求里残留的 label 键不得再进注册表（否则字段会复活）。"""
        merged = _merge([{**_BASE, "label": "DeepSeek"}], [])
        assert "label" not in merged[0]

    def test_params_keep_existing_on_none(self) -> None:
        """None = 沿用同 id 旧值（不覆盖、不清空）；显式值即覆盖。"""
        existing = _merge([{**_BASE, "reasoning_effort": "high"}], [])
        assert (
            _merge([{**_BASE, "reasoning_effort": None}], existing)[0]["reasoning_effort"] == "high"
        )
        assert (
            _merge([{**_BASE, "reasoning_effort": "low"}], existing)[0]["reasoning_effort"] == "low"
        )


class TestProviderConfigMerging:
    """供应商段（2026-10-18 供应商中心化重构）。"""

    def test_duplicate_ids_are_rejected(self) -> None:
        """两个供应商撞同一个 id 时写侧会合并成一条、模型却全保留。

        真实事故（2026-11-10）：前端按页内序号生成 `p-new-1`，刷新页面后与已落盘的
        id 撞名，导致「MiniMax 供应商名下挂着 5 个 Kimi 模型」。撞名必须整单拒绝。
        """
        with pytest.raises(ConfigurationError, match="供应商 id 重复"):
            ForgeService._merge_provider_configs(
                [
                    {
                        "id": "p-dup",
                        "provider": "moonshot",
                        "base_url": "https://api.moonshot.cn/v1",
                    },
                    {
                        "id": "p-dup",
                        "provider": "minimax",
                        "base_url": "https://api.minimaxi.com/v1",
                    },
                ],
                [],
            )

    def test_id_generated_when_absent(self) -> None:
        merged = ForgeService._merge_provider_configs(
            [{"provider": "deepseek", "base_url": "https://a"}], []
        )
        assert merged[0]["id"].startswith("p-")

    def test_api_key_inherits_on_empty(self) -> None:
        """前端只有脱敏值，回传空串是常态——必须沿用旧密钥而非清空（MUST-19）。"""
        existing = ForgeService._merge_provider_configs(
            [{"id": "p-1", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-old"}],
            [],
        )
        merged = ForgeService._merge_provider_configs(
            [{"id": "p-1", "provider": "deepseek", "base_url": "https://a", "api_key": ""}],
            existing,
        )
        assert merged[0]["api_key"] == "sk-old"

    def test_explicit_key_overrides(self) -> None:
        existing = ForgeService._merge_provider_configs(
            [{"id": "p-1", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-old"}],
            [],
        )
        merged = ForgeService._merge_provider_configs(
            [{"id": "p-1", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-new"}],
            existing,
        )
        assert merged[0]["api_key"] == "sk-new"

    def test_api_key_inherits_by_endpoint_when_id_mismatches(self) -> None:
        """安全网：id 对不上（如前端自行生成了新 id）时，同端点的旧密钥仍要接住。

        只靠 id 回落会让密钥被静默清空——用户没有任何提示，却在刷新时开始报鉴权失败。
        """
        existing = ForgeService._merge_provider_configs(
            [
                {
                    "id": "p-old",
                    "provider": "deepseek",
                    "base_url": "https://a",
                    "api_key": "sk-keep",
                }
            ],
            [],
        )
        merged = ForgeService._merge_provider_configs(
            [{"id": "p-new", "provider": "deepseek", "base_url": "https://a"}], existing
        )
        assert merged[0]["api_key"] == "sk-keep"

    def test_api_key_not_inherited_across_endpoints(self) -> None:
        """不同端点的密钥绝不串用——官方与中转往往是两把不同的钥匙。"""
        existing = ForgeService._merge_provider_configs(
            [{"id": "p-a", "provider": "deepseek", "base_url": "https://a", "api_key": "sk-a"}],
            [],
        )
        merged = ForgeService._merge_provider_configs(
            [{"id": "p-b", "provider": "deepseek", "base_url": "https://b"}], existing
        )
        assert merged[0]["api_key"] == ""

    def test_authoritative_list_drops_unlisted(self) -> None:
        """权威列表语义：未出现的既有供应商被删除（级联，用户裁定）。"""
        existing = ForgeService._merge_provider_configs(
            [
                {"id": "p-keep", "provider": "deepseek", "base_url": "https://a"},
                {"id": "p-drop", "provider": "deepseek", "base_url": "https://b"},
            ],
            [],
        )
        merged = ForgeService._merge_provider_configs(
            [{"id": "p-keep", "provider": "deepseek", "base_url": "https://a"}], existing
        )
        assert [r["id"] for r in merged] == ["p-keep"]


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
        assert PROVIDER_SPECS["deepseek"].max_context_length == 1_048_576
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
            "deepseek": 1_048_576,  # 官方 /models 返回 context_window=1048576
            "zhipu": 200000,  # 官方文档 GLM-4.6
            "moonshot": 262_144,  # 官方 K2 系列 256K；K3 的 1M 在模型级登记
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
        ):
            assert PROVIDER_SPECS[key].max_context_length is None, key
            assert PROVIDER_SPECS[key].context_window_tiers == (), key
