"""模型目录落库测试：写入→读回、复合主键覆盖、损坏数据不崩。

用临时 SQLite 文件（``DEVPROMPT_SETTINGS_DB`` 指向），不碰用户真实数据。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from devprompt_ai.domain.model_catalog.catalog import ModelCatalogItem
from devprompt_ai.memory.model_catalog_store import (
    ModelCatalogStoreError,
    catalog_db_enabled,
    read_model_catalog,
    write_model_catalog,
)


@pytest.fixture
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "catalog.db"
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(path))
    yield path


def _item(model_id: str, window: int | None = 1_048_576) -> ModelCatalogItem:
    return ModelCatalogItem(
        model_id=model_id,
        label=f"展示 {model_id}",
        max_context_length=window,
        context_window_tiers=(window,) if window else (),
        source="remote",
    )


def _set_payload(db_file: Path, payload: str) -> None:
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE model_catalog SET payload_json = ?", (payload,))
    conn.commit()
    conn.close()


class TestRoundTrip:
    def test_write_then_read(self, db_file: Path) -> None:
        fetched_at = write_model_catalog("deepseek", "https://api.deepseek.com", [_item("a")])
        assert fetched_at
        items, read_at = read_model_catalog("deepseek", "https://api.deepseek.com")
        assert [i.model_id for i in items] == ["a"]
        assert items[0].max_context_length == 1_048_576
        assert items[0].context_window_tiers == (1_048_576,)
        assert items[0].source == "remote"
        assert read_at == fetched_at

    def test_survives_new_connection(self, db_file: Path) -> None:
        """落库的意义就是重启不丢——这里用「重新读」近似新进程。"""
        write_model_catalog("deepseek", "u1", [_item("a")])
        assert len(read_model_catalog("deepseek", "u1")[0]) == 1

    def test_upsert_replaces_snapshot(self, db_file: Path) -> None:
        write_model_catalog("deepseek", "u1", [_item("a"), _item("b")])
        write_model_catalog("deepseek", "u1", [_item("b")])
        assert [i.model_id for i in read_model_catalog("deepseek", "u1")[0]] == ["b"]

    def test_provider_and_url_are_independent_keys(self, db_file: Path) -> None:
        write_model_catalog("deepseek", "u1", [_item("a")])
        write_model_catalog("zhipu", "u1", [_item("z")])
        write_model_catalog("deepseek", "u2", [_item("c")])
        assert [i.model_id for i in read_model_catalog("deepseek", "u1")[0]] == ["a"]
        assert [i.model_id for i in read_model_catalog("zhipu", "u1")[0]] == ["z"]
        assert [i.model_id for i in read_model_catalog("deepseek", "u2")[0]] == ["c"]

    def test_unknown_key_returns_empty_without_error(self, db_file: Path) -> None:
        assert read_model_catalog("nobody", "nowhere") == ([], None)

    def test_missing_db_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "absent.db"))
        assert read_model_catalog("deepseek", "u1") == ([], None)


class TestRobustness:
    def test_corrupted_payload_yields_empty(self, db_file: Path) -> None:
        write_model_catalog("deepseek", "u1", [_item("a")])
        _set_payload(db_file, "{")
        items, fetched_at = read_model_catalog("deepseek", "u1")
        assert items == []
        assert fetched_at is not None, "时间戳仍可读，便于 UI 提示上次刷新时间"

    def test_malformed_entries_skipped(self, db_file: Path) -> None:
        write_model_catalog("deepseek", "u1", [_item("a")])
        _set_payload(db_file, '[{"model_id": ""}, {"model_id": "ok", "source": "static"}]')
        items, _ = read_model_catalog("deepseek", "u1")
        assert [i.model_id for i in items] == ["ok"]
        assert items[0].source == "static"

    def test_unknown_window_survives(self, db_file: Path) -> None:
        write_model_catalog("deepseek", "u1", [_item("a", window=None)])
        items, _ = read_model_catalog("deepseek", "u1")
        assert items[0].max_context_length is None
        assert items[0].context_window_tiers == ()


class TestDisabled:
    def test_disabled_db_raises_on_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", "")
        with pytest.raises(ModelCatalogStoreError, match="禁用"):
            write_model_catalog("deepseek", "u1", [_item("a")])

    def test_disabled_db_read_is_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", "")
        assert read_model_catalog("deepseek", "u1") == ([], None)
        assert catalog_db_enabled() is False


class TestNoSecretsInSchema:
    def test_table_has_no_key_column(self, db_file: Path) -> None:
        """表结构里绝不能出现 api_key 之类的列（MUST-19）。"""
        write_model_catalog("deepseek", "u1", [_item("a")])
        conn = sqlite3.connect(str(db_file))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(model_catalog)")}
        conn.close()
        assert cols == {"provider_key", "base_url", "payload_json", "fetched_at"}
