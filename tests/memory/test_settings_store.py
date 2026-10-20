"""F-604 设置持久化测试（T6-11）：settings.json 文件（0600）+ app_settings 表 + 合并加载。"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

import pytest

from devprompt_ai.memory import settings_store
from devprompt_ai.memory.settings_store import (
    SettingsStoreError,
    load_local_settings,
    read_model_registry,
    read_model_settings,
    read_process_settings,
    write_model_registry,
    write_model_settings,
    write_process_settings,
)


@pytest.fixture
def local_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """测试隔离：设置文件与设置库指向 tmp（DEVPROMPT_SETTINGS_* 环境变量路径覆盖）。"""
    settings_file = tmp_path / "settings.json"
    db = tmp_path / "settings.db"
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(db))
    return settings_file, db


@pytest.mark.skipif(os.name == "nt", reason="Windows 无 POSIX 权限位（0600 语义仅 POSIX）")
def test_write_model_settings_masks_file_permissions(
    local_paths: tuple[Path, Path],
) -> None:
    settings_file, _ = local_paths
    write_model_settings({"base_url": "https://api.x", "api_key": "sk-plain-1234567890"})
    mode = stat.S_IMODE(os.stat(settings_file).st_mode)
    assert mode == 0o600  # MUST-19：密钥文件仅属主可读写
    doc = json.loads(settings_file.read_text(encoding="utf-8"))
    # 明文密钥只进设置文件（不入库不进日志），GET 回显由 service 脱敏
    assert doc["model_service"]["api_key"] == "sk-plain-1234567890"


def test_write_model_settings_merges_and_none_keeps(
    local_paths: tuple[Path, Path],
) -> None:
    write_model_settings({"base_url": "https://api.x", "api_key": "sk-a-1234567890"})
    write_model_settings({"model_id": "m1", "api_key": None})  # None 不覆盖既有值
    section = read_model_settings()
    assert section["base_url"] == "https://api.x"
    assert section["api_key"] == "sk-a-1234567890"
    assert section["model_id"] == "m1"


def test_write_process_settings_upsert(local_paths: tuple[Path, Path]) -> None:
    write_process_settings({"followup_soft_round_guard": 10, "telemetry": True})
    write_process_settings({"followup_soft_round_guard": 8})
    values = read_process_settings()
    assert values["followup_soft_round_guard"] == 8
    assert values["telemetry"] is True  # 未提及键保持不变


def test_load_local_settings_merges_both_sources(
    local_paths: tuple[Path, Path],
) -> None:
    write_model_settings({"base_url": "https://api.x"})
    write_process_settings({"telemetry": False})
    local = load_local_settings()
    assert local["model_service"]["base_url"] == "https://api.x"
    assert local["process"]["telemetry"] is False


def test_missing_sources_graceful(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "absent.db"))
    assert read_model_settings() == {}
    assert read_process_settings() == {}
    assert load_local_settings() == {"model_service": {}, "process": {}}


def test_disabled_sources_reject_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", "")
    with pytest.raises(SettingsStoreError):
        write_model_settings({"base_url": "x"})
    with pytest.raises(SettingsStoreError):
        write_process_settings({"telemetry": True})
    assert read_model_settings() == {}
    assert read_process_settings() == {}


def test_process_values_json_roundtrip(local_paths: tuple[Path, Path]) -> None:
    """流程参数值 JSON 编码存储：浮点/布尔往返类型不失真。"""
    write_process_settings({"followup_cost_budget": 2500.5, "telemetry": False})
    values: dict[str, Any] = read_process_settings()
    assert values["followup_cost_budget"] == 2500.5
    assert values["telemetry"] is False
    _, db = local_paths
    conn = sqlite3.connect(str(db))
    try:
        raw = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'followup_cost_budget'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert json.loads(raw) == 2500.5  # 值为 JSON 编码文本


def test_settings_module_paths_default_to_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认路径落在 ~/.devprompt-ai/（与 db_path 同居）；显式路径覆盖生效。"""
    monkeypatch.delenv("DEVPROMPT_SETTINGS_FILE", raising=False)
    monkeypatch.delenv("DEVPROMPT_SETTINGS_DB", raising=False)
    assert settings_store._settings_file_path() is not None
    assert str(settings_store._settings_file_path()).endswith("settings.json")
    assert str(settings_store._db_path()).endswith("devprompt.db")


def test_read_model_registry_missing_and_corrupt(
    local_paths: tuple[Path, Path],
) -> None:
    """注册表缺失/损坏均静默返回空表（列表降级为空，不影响 model_service）。"""
    settings_file, _ = local_paths
    assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}
    settings_file.write_text("{not-json", encoding="utf-8")
    assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}


def test_write_model_registry_roundtrip_and_active_keeps(
    local_paths: tuple[Path, Path],
) -> None:
    """整表写入回读一致；active_model_id=None 不覆盖既有激活位；与 model_service 共存。"""
    settings_file, _ = local_paths
    entries = [
        {
            "id": "m-1",
            "provider": "DeepSeek",
            "base_url": "https://a",
            "api_key": "sk-a-1234567890",
            "model_id": "deepseek-flash",
        },
    ]
    write_model_registry(entries, "m-1")
    write_model_settings({"base_url": "https://a"})  # 同文件共存
    registry = read_model_registry()
    assert registry["models"][0]["id"] == "m-1"
    assert registry["active_model_id"] == "m-1"
    assert read_model_settings()["base_url"] == "https://a"

    write_model_registry(entries, None)  # None 保留既有激活位
    assert read_model_registry()["active_model_id"] == "m-1"
    doc = json.loads(settings_file.read_text(encoding="utf-8"))
    # 2026-10-18 起密钥只存供应商段一份，明文仍仅落设置文件（MUST-19）
    assert doc["providers"][0]["api_key"] == "sk-a-1234567890"
    assert "api_key" not in doc["models"][0]


def test_write_model_registry_disabled_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
    with pytest.raises(SettingsStoreError):
        write_model_registry([], None)
