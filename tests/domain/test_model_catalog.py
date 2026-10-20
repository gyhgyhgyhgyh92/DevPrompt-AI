"""模型目录领域层测试：合并、回落、标注三条语义链。

覆盖的关键不变量（F-921 验收）：
① 动态优先——远端有窗口时静态值不覆盖；
② 档位恒 ≤ 窗口上限；
③ 窗口全程未知 → None（不判定、不告警）；
④ 存量模型不在目录时被标注而非丢弃。
"""

from __future__ import annotations

from devprompt_ai.domain.model_catalog import (
    ModelCatalogItem,
    RemoteModelInfo,
    effective_context_window,
    find_item,
    mark_stale_models,
    merge_catalog,
    static_catalog,
)


class TestCleanTiers:
    def test_illegal_tier_is_dropped(self) -> None:
        merged = merge_catalog(
            [
                RemoteModelInfo(
                    model_id="m-1",
                    max_context_length=200_000,
                    context_window_tiers=(1_048_576, 200_000, 64_000),
                )
            ],
            provider="deepseek",
        )
        tiers = find_item(merged, "m-1").context_window_tiers
        assert 1_048_576 not in tiers, "超过窗口上限的档位必须丢弃（防假安全感）"
        assert tiers == (64_000, 131_072, 200_000), "厂商档位与标准阶梯取并集"

    def test_unknown_window_yields_no_tiers(self) -> None:
        merged = merge_catalog(
            [RemoteModelInfo(model_id="m-1", context_window_tiers=(64_000,))],
            provider="yi",
        )
        item = find_item(merged, "m-1")
        assert item.context_window_tiers == (), "窗口未知就没有合法档位可言"
        assert item.max_context_length is None


class TestMergeCatalog:
    def test_remote_window_wins_over_static(self) -> None:
        """动态优先：端点给了窗口就不能被静态值覆盖。"""
        merged = merge_catalog(
            [RemoteModelInfo(model_id="deepseek-v4-pro", max_context_length=1_048_576)],
            provider="deepseek",
            static_items=static_catalog("deepseek"),
        )
        item = find_item(merged, "deepseek-v4-pro")
        assert item.source == "remote"
        assert item.max_context_length == 1_048_576

    def test_static_fills_missing_window(self) -> None:
        """远端只给 id 时，窗口回落静态模型级值。"""
        merged = merge_catalog(
            [RemoteModelInfo(model_id="deepseek-flash")],
            provider="deepseek",
            static_items=static_catalog("deepseek"),
        )
        item = find_item(merged, "deepseek-flash")
        assert item.source == "remote"
        assert item.max_context_length == 1_048_576
        assert item.context_window_tiers == (131_072, 262_144, 524_288, 1_048_576)

    def test_empty_remote_falls_back_to_static(self) -> None:
        merged = merge_catalog([], provider="deepseek")
        assert merged, "拉不到时静态表必须顶上，下拉不能空"
        assert all(item.source == "static" for item in merged)
        assert {item.model_id for item in merged} == {"deepseek-flash", "deepseek-v4-pro"}

    def test_malformed_entry_is_dropped(self) -> None:
        merged = merge_catalog(
            [RemoteModelInfo(model_id="  "), RemoteModelInfo(model_id="ok")],
            provider="deepseek",
        )
        assert [item.model_id for item in merged] == ["ok"]

    def test_display_name_used_when_present(self) -> None:
        merged = merge_catalog(
            [RemoteModelInfo(model_id="m-1", display_name="展示名")], provider="deepseek"
        )
        assert merged[0].label == "展示名"

    def test_label_falls_back_to_model_id(self) -> None:
        merged = merge_catalog([RemoteModelInfo(model_id="m-1")], provider="deepseek")
        assert merged[0].label == "m-1"


class TestMarkStaleModels:
    def test_configured_model_absent_is_kept_and_flagged(self) -> None:
        catalog = merge_catalog([RemoteModelInfo(model_id="a")], provider="deepseek")
        result = mark_stale_models(catalog, ["a", "已下架的模型"], provider="deepseek")
        assert result[0].model_id == "已下架的模型"
        assert result[0].is_stale is True
        assert result[1].model_id == "a", "存量项置顶后在目录项之后"

    def test_present_model_is_not_flagged(self) -> None:
        catalog = merge_catalog([RemoteModelInfo(model_id="a")], provider="deepseek")
        result = mark_stale_models(catalog, ["a"], provider="deepseek")
        assert all(not item.is_stale for item in result)

    def test_blank_ids_ignored(self) -> None:
        catalog = merge_catalog([RemoteModelInfo(model_id="a")], provider="deepseek")
        assert mark_stale_models(catalog, ["", "  "]) == list(catalog)


class TestEffectiveContextWindow:
    def _catalog(self) -> list[ModelCatalogItem]:
        return merge_catalog(
            [
                RemoteModelInfo(
                    model_id="m-1",
                    max_context_length=1_048_576,
                    context_window_tiers=(200_000, 1_048_576),
                )
            ],
            provider="deepseek",
        )

    def test_selected_tier_wins(self) -> None:
        assert effective_context_window("deepseek", "m-1", 200_000, self._catalog()) == 200_000

    def test_ladder_tier_below_nominal_wins(self) -> None:
        """阶梯档位低于标称窗口也要生效，否则 DeepSeek 的告警预算永远调不动。"""
        assert effective_context_window("deepseek", "m-1", 262_144, self._catalog()) == 262_144

    def test_ladder_tier_works_on_static_chain(self) -> None:
        """catalog 里没有该模型时阶梯档位同样生效（回落链两跳口径一致）。"""
        assert effective_context_window("deepseek", "deepseek-flash", 262_144, []) == 262_144

    def test_no_selection_uses_nominal(self) -> None:
        assert effective_context_window("deepseek", "m-1", None, self._catalog()) == 1_048_576

    def test_illegal_tier_falls_back_to_nominal(self) -> None:
        assert effective_context_window("deepseek", "m-1", 999, self._catalog()) == 1_048_576

    def test_unknown_model_uses_static_chain(self) -> None:
        assert effective_context_window("deepseek", "deepseek-flash", None, []) == 1_048_576

    def test_fully_unknown_returns_none(self) -> None:
        assert effective_context_window("yi", "某个没登记的模型", None, []) is None

    def test_catalog_entry_without_window_stays_none(self) -> None:
        """目录里有该模型但窗口未登记 → 不拿厂商级值来凑（口径不同）。"""
        catalog = merge_catalog([RemoteModelInfo(model_id="m-2")], provider="yi")
        assert effective_context_window("yi", "m-2", None, catalog) is None

    def test_model_id_case_insensitive(self) -> None:
        assert effective_context_window("deepseek", "M-1", 200_000, self._catalog()) == 200_000
