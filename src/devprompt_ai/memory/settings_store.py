"""F-604 设置持久化（T6-11 后端）：模型服务 → settings.json（0600）；流程参数 → app_settings 表。

MUST-19 修订后语义（真源 §13 2026-10-12 批准）：密钥不入库（SQLite）、不进日志；
本地设置文件（0600 权限）为密钥唯一落盘处。AppConfig 加载链：init > 环境变量 >
本地设置（本模块） > .env > 默认值——环境变量优先，本地设置兜底。

SQL 仅在 memory/（MUST-06）。sqlite3 同步 API 的使用处经 asyncio.to_thread 包装（MUST-13）。
测试隔离：DEVPROMPT_SETTINGS_FILE / DEVPROMPT_SETTINGS_DB 环境变量可覆盖路径，空值禁用。
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from devprompt_ai.memory.schema import SETTINGS_DDL

_DEFAULT_SETTINGS_FILE = "~/.devprompt-ai/settings.json"
_DEFAULT_DB = "~/.devprompt-ai/devprompt.db"
_BUSY_TIMEOUT_MS = 5000
_FILE_PERMISSIONS = 0o600


class SettingsStoreError(RuntimeError):
    """设置落盘失败（本地设置被禁用 / 磁盘不可写）。"""


def _settings_file_path() -> Path | None:
    raw = os.environ.get("DEVPROMPT_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE)
    return Path(raw).expanduser() if raw else None


def _db_path() -> Path | None:
    raw = os.environ.get("DEVPROMPT_SETTINGS_DB", _DEFAULT_DB)
    return Path(raw).expanduser() if raw else None


def read_model_settings() -> dict[str, Any]:
    """读 settings.json 的 model_service 段；缺失/损坏静默返回 {}（默认值兜底）。"""
    path = _settings_file_path()
    if path is None or not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    section = doc.get("model_service")
    return dict(section) if isinstance(section, dict) else {}


def write_model_settings(values: dict[str, Any]) -> None:
    """合并写 settings.json（None 值不覆盖既有值；原子替换 + 0600 权限）。"""
    path = _settings_file_path()
    if path is None:
        raise SettingsStoreError("设置文件已禁用（DEVPROMPT_SETTINGS_FILE 为空），无法写模型配置")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = {}
    section = dict(doc.get("model_service") or {})
    section.update({k: v for k, v in values.items() if v is not None})
    doc["model_service"] = section
    # 原子写（tempfile + replace）避免半成品文件；随后强制 0600
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except OSError as exc:
        Path(tmp_name).unlink(missing_ok=True)
        raise SettingsStoreError(f"设置文件写入失败：{exc}") from exc
    os.chmod(path, _FILE_PERMISSIONS)


def read_process_settings() -> dict[str, Any]:
    """读 app_settings 表全部键值（JSON 编码存储）；库/表缺失静默返回 {}。"""
    path = _db_path()
    if path is None or not path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
        try:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    out: dict[str, Any] = {}
    for key, raw in rows:
        try:
            out[str(key)] = json.loads(raw)
        except json.JSONDecodeError:
            continue
    return out


def write_process_settings(values: dict[str, Any]) -> None:
    """写 app_settings 表（值 JSON 编码；upsert 幂等）。"""
    path = _db_path()
    if path is None:
        raise SettingsStoreError("设置库已禁用（DEVPROMPT_SETTINGS_DB 为空），无法写流程参数")
    path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
        try:
            conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            conn.executescript(SETTINGS_DDL)
            for key, value in values.items():
                if value is None:
                    continue
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            conn.commit()
        finally:
            conn.close()

    try:
        _run()
    except sqlite3.Error as exc:
        raise SettingsStoreError(f"流程参数写入失败：{exc}") from exc


def load_local_settings() -> dict[str, Any]:
    """AppConfig 本地设置合并源（config.py 调用；任何缺失静默跳过，环境变量仍可覆盖）。"""
    return {"model_service": read_model_settings(), "process": read_process_settings()}
