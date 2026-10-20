"""模型目录测试：契约形状 + service 行为（不联网）。

重点验证用户裁定的两条语义：
1. **刷新失败不清空**——返回上次落库快照 + warning；
2. **明文密钥不进请求体**——请求体只有 entry_id，且不落库。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import CatalogFetchError, ConfigurationError, StateError
from devprompt_ai.domain.model_catalog.catalog import ModelCatalogItem
from devprompt_ai.domain.model_catalog.ports import RemoteModelInfo
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.service import ForgeService, build_default

_SECRET = "sk-should-not-appear"
_BASE_URL = "https://api.example.com/v1"


class _StubFetcher:
    """假拉取器：按脚本决定成功 / 失败，不联网。"""

    def __init__(
        self, result: list[RemoteModelInfo] | None = None, error: Exception | None = None
    ) -> None:
        self.result = result or []
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, *, base_url: str, api_key: str, timeout: float) -> list[RemoteModelInfo]:
        self.calls.append((base_url, api_key))
        if self.error is not None:
            raise self.error
        return self.result


def _build_sync() -> ForgeService:
    import asyncio

    return asyncio.run(build_default(AppConfig(_env_file=None)))  # type: ignore[call-arg]


def _entry(base_url: str = _BASE_URL, model_id: str = "m-1") -> dict[str, object]:
    return {
        "id": "m-1",
        "label": "示例",
        "provider": "deepseek",
        "base_url": base_url,
        "api_key": _SECRET,
        "model_id": model_id,
    }


def _provider_id() -> str:
    """读出条目 ``m-1`` 迁移后归属的供应商 id（2026-10-18 供应商中心化）。"""
    from devprompt_ai.memory.settings_store import read_model_registry

    return str(read_model_registry()["providers"][0]["id"])


@pytest.fixture
def svc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ForgeService]:
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "db.sqlite"))
    service = _build_sync()
    service._catalog_fetcher = _StubFetcher()
    yield service


class TestContractShape:
    def test_paths_present(self) -> None:
        paths = create_app().openapi()["paths"]
        assert "get" in paths["/api/v1/settings/models/catalog"]
        assert "post" in paths["/api/v1/settings/models/catalog/refresh"]

    def test_request_body_has_no_api_key(self) -> None:
        """明文密钥绝不能出现在请求体契约里（MUST-19）。"""
        schemas = create_app().openapi()["components"]["schemas"]
        assert set(schemas["ModelCatalogRefreshRequest"]["properties"]) == {"provider_id"}

    def test_response_declares_warning_and_items(self) -> None:
        props = create_app().openapi()["components"]["schemas"]["ModelCatalogResponse"][
            "properties"
        ]
        assert {"provider", "base_url", "fetched_at", "models", "warning"} <= set(props)


class TestRefresh:
    async def test_success_persists_snapshot(self, svc: ForgeService) -> None:
        from devprompt_ai.memory.model_catalog_store import read_model_catalog

        svc._catalog_fetcher = _StubFetcher(
            [RemoteModelInfo(model_id="new-model", max_context_length=99)]
        )
        result = await svc.refresh_model_catalog("deepseek", _BASE_URL, _SECRET, request_id="r")
        assert result["warning"] is None
        assert [m["model_id"] for m in result["models"]] == ["new-model"]

        stored, fetched_at = read_model_catalog("deepseek", _BASE_URL)
        assert [i.model_id for i in stored] == ["new-model"]
        assert fetched_at
        assert _SECRET not in str(stored), "落库内容绝不能含 api_key（MUST-19）"

    async def test_failed_refresh_keeps_previous_snapshot(self, svc: ForgeService) -> None:
        """用户裁定：拉不到就保留上次结果 + warning，绝不清空。"""
        from devprompt_ai.memory.model_catalog_store import write_model_catalog

        write_model_catalog(
            "deepseek",
            _BASE_URL,
            [ModelCatalogItem(model_id="old-model", label="旧", max_context_length=1)],
        )
        svc._catalog_fetcher = _StubFetcher([], CatalogFetchError("限流：请稍后重试"))
        result = await svc.refresh_model_catalog("deepseek", _BASE_URL, _SECRET, request_id="r")
        assert result["warning"] == "限流：请稍后重试"
        assert [m["model_id"] for m in result["models"]] == ["old-model"]

    async def test_failure_without_snapshot_falls_back_to_static(self, svc: ForgeService) -> None:
        svc._catalog_fetcher = _StubFetcher([], CatalogFetchError("端点不支持"))
        result = await svc.refresh_model_catalog("deepseek", _BASE_URL, _SECRET, request_id="r")
        assert result["warning"]
        assert [m["model_id"] for m in result["models"]] == ["deepseek-flash", "deepseek-v4-pro"]
        assert all(m["source"] == "static" for m in result["models"])

    async def test_missing_fetcher_reports_instead_of_raising(self, svc: ForgeService) -> None:
        svc._catalog_fetcher = None
        result = await svc.refresh_model_catalog("deepseek", _BASE_URL, _SECRET, request_id="r")
        assert result["warning"] and "未接入" in result["warning"]
        assert result["models"], "没有拉取器时仍要给出可用下拉（静态兜底）"

    async def test_key_handed_to_fetcher_only(self, svc: ForgeService) -> None:
        fetcher = _StubFetcher([RemoteModelInfo(model_id="m")])
        svc._catalog_fetcher = fetcher
        await svc.refresh_model_catalog("deepseek", _BASE_URL, _SECRET, request_id="r")
        assert fetcher.calls == [(_BASE_URL, _SECRET)]


class TestReadCatalog:
    async def test_read_is_offline_and_marks_stale(self, svc: ForgeService) -> None:
        """读目录不联网；已配但不在列表的模型会被置顶标注。"""
        from devprompt_ai.memory.model_catalog_store import write_model_catalog
        from devprompt_ai.memory.settings_store import write_model_registry

        write_model_registry([_entry(model_id="retired-model")], None)
        write_model_catalog(
            "deepseek", _BASE_URL, [ModelCatalogItem(model_id="live", label="在线")]
        )
        result = await svc.read_model_catalog("deepseek", _BASE_URL, request_id="r")
        assert result["models"][0]["model_id"] == "retired-model"
        assert result["models"][0]["is_stale"] is True
        assert result["models"][1]["model_id"] == "live"

    async def test_read_without_snapshot_falls_back_to_static(self, svc: ForgeService) -> None:
        result = await svc.read_model_catalog("deepseek", "https://unknown", request_id="r")
        assert [m["model_id"] for m in result["models"]] == ["deepseek-flash", "deepseek-v4-pro"]
        assert result["fetched_at"] is None


class TestCatalogTarget:
    def test_unknown_provider_rejected(self, svc: ForgeService) -> None:
        with pytest.raises(StateError, match="供应商不存在"):
            svc.provider_catalog_target("p-nope")

    def test_provider_without_entry_still_resolvable(self, svc: ForgeService) -> None:
        """刚配好、还没勾选任何模型的供应商也必须能刷新（多选流程第一步）。"""
        from devprompt_ai.memory.settings_store import read_model_registry, write_model_registry

        write_model_registry([], None, [{"provider": "deepseek", "base_url": _BASE_URL}])
        fresh = read_model_registry()["providers"][0]["id"]
        assert svc.provider_catalog_target(fresh, with_key=True) == ("deepseek", _BASE_URL, "")

    def test_blank_base_url_rejected(self, svc: ForgeService) -> None:
        from devprompt_ai.memory.settings_store import write_model_registry

        write_model_registry([_entry(base_url="")], None)
        with pytest.raises(ConfigurationError, match="接口地址"):
            svc.provider_catalog_target(_provider_id())

    def test_key_returned_only_when_asked(self, svc: ForgeService) -> None:
        from devprompt_ai.memory.settings_store import write_model_registry

        write_model_registry([_entry()], None)
        provider_id = _provider_id()
        assert svc.provider_catalog_target(provider_id) == ("deepseek", _BASE_URL, "")
        assert svc.provider_catalog_target(provider_id, with_key=True) == (
            "deepseek",
            _BASE_URL,
            _SECRET,
        )


class TestEffectiveWindow:
    def test_dynamic_window_is_used(self, svc: ForgeService) -> None:
        from devprompt_ai.memory.model_catalog_store import write_model_catalog
        from devprompt_ai.memory.settings_store import write_model_registry

        write_model_registry([_entry()], None)  # 端点从注册表条目取
        write_model_catalog(
            "deepseek",
            _BASE_URL,
            [ModelCatalogItem(model_id="m-1", label="m", max_context_length=2_000_000)],
        )
        assert svc.effective_window("deepseek", "m-1", None) == 2_000_000

    def test_selected_tier_wins(self, svc: ForgeService) -> None:
        from devprompt_ai.memory.model_catalog_store import write_model_catalog
        from devprompt_ai.memory.settings_store import write_model_registry

        write_model_registry([_entry()], None)
        write_model_catalog(
            "deepseek",
            _BASE_URL,
            [
                ModelCatalogItem(
                    model_id="m-1",
                    label="m",
                    max_context_length=2_000_000,
                    context_window_tiers=(500_000, 2_000_000),
                )
            ],
        )
        assert svc.effective_window("deepseek", "m-1", 500_000) == 500_000

    def test_unknown_stays_none(self, svc: ForgeService) -> None:
        assert svc.effective_window("yi", "从未登记的模型", None) is None
