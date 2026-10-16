"""F-604 设置持久化（T6-11 后端）：模型服务 → settings.json（0600）；流程参数 → app_settings 表。

MUST-19 修订后语义（真源 §13 2026-10-12 批准）：密钥不入库（SQLite）、不进日志；
本地设置文件（0600 权限）为密钥唯一落盘处。AppConfig 加载链：init > 环境变量 >
本地设置（本模块） > .env > 默认值——环境变量优先，本地设置兜底。

同一文件还承载多模型注册表（F-604，2026-10-13）：`models`（条目列表）+ `active_model_id`
（当前生效条目）——各条目 api_key 与 model_service 同处 0600 文件，密钥边界不变；
`model_service` 段仍是 AppConfig 的唯一取值来源（激活条目由 service 层镜像写入）。

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

from devprompt_ai.domain.model_migration import normalize_registry
from devprompt_ai.memory.schema import SETTINGS_DDL

_DEFAULT_SETTINGS_FILE = "~/.devprompt-ai/settings.json"
_DEFAULT_DB = "~/.devprompt-ai/devprompt.db"
_BUSY_TIMEOUT_MS = 5000
_FILE_PERMISSIONS = 0o600

# 多模型注册表在 settings.json 中的键（F-604：模型列表 + 当前生效条目 id）
_REGISTRY_KEY = "models"
_ACTIVE_KEY = "active_model_id"


class SettingsStoreError(RuntimeError):
    """设置落盘失败（本地设置被禁用 / 磁盘不可写）。"""


def _settings_file_path() -> Path | None:
    raw = os.environ.get("DEVPROMPT_SETTINGS_FILE", _DEFAULT_SETTINGS_FILE)
    return Path(raw).expanduser() if raw else None


def _db_path() -> Path | None:
    raw = os.environ.get("DEVPROMPT_SETTINGS_DB", _DEFAULT_DB)
    return Path(raw).expanduser() if raw else None


def _read_doc() -> dict[str, Any]:
    """读 settings.json 全文；文件缺失/损坏/非对象静默返回 {}（调用方按需兜底）。"""
    path = _settings_file_path()
    if path is None or not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_doc(doc: dict[str, Any], disabled_message: str) -> None:
    """原子替换写 settings.json 全文并强制 0600（tempfile + replace，避免半成品文件）。"""
    path = _settings_file_path()
    if path is None:
        raise SettingsStoreError(disabled_message)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except OSError as exc:
        Path(tmp_name).unlink(missing_ok=True)
        raise SettingsStoreError(f"设置文件写入失败：{exc}") from exc
    os.chmod(path, _FILE_PERMISSIONS)


def read_model_settings() -> dict[str, Any]:
    """读 settings.json 的 model_service 段；缺失/损坏静默返回 {}（默认值兜底）。"""
    section = _read_doc().get("model_service")
    return dict(section) if isinstance(section, dict) else {}


def write_model_settings(values: dict[str, Any]) -> None:
    """合并写 settings.json 的 model_service 段（None 值不覆盖既有值；原子替换 + 0600）。"""
    doc = _read_doc()
    section = dict(doc.get("model_service") or {})
    section.update({k: v for k, v in values.items() if v is not None})
    doc["model_service"] = section
    _write_doc(doc, "设置文件已禁用（DEVPROMPT_SETTINGS_FILE 为空），无法写模型配置")


def read_model_registry() -> dict[str, Any]:
    """读 settings.json 的模型注册表：返回 ``{"models": [...], "active_model_id": str}``。

    **读时归一化**（2026-09-17模型管理迁移）：逐条经 `domain.model_migration.normalize_entry`
    补齐 `capabilities` / `param_overrides`，因此六字段的旧条目无需迁移脚本即可使用，
    且在下次保存时自动升级为新结构。归一化**永不抛异常**——数据文件由用户手工编辑也可能出错，
    读取失败不该让配置丢失或让服务起不来。

    缺失/损坏静默返回空表（列表展示降级为空，不影响 model_service 生效配置）。
    """
    doc = _read_doc()
    raw_models = doc.get(_REGISTRY_KEY)
    models = normalize_registry(raw_models)
    active = doc.get(_ACTIVE_KEY)
    active_id = active if isinstance(active, str) else ""
    # 激活位指向已被删除的条目时回落为空，避免上层拿到悬空引用
    if active_id and not any(str(item.get("id")) == active_id for item in models):
        active_id = ""
    return {"models": models, "active_model_id": active_id}


def write_model_registry(models: list[dict[str, Any]], active_model_id: str | None) -> None:
    """整表写注册表：``models`` 全量替换；``active_model_id`` None 不覆盖既有值。

    写入前统一经 :func:`normalize_registry` 归一化——「读时补、写时全」，
    保证落盘结构始终是完整的（不会出现只存了六字段的老结构）。
    非字典条目被静默丢弃（与既有读侧行为一致：脏数据不该让整个写入失败）。

    与 ``write_model_settings`` 共用同一原子替换 + 0600 实现（MUST-19：密钥唯一落盘处不变）。
    """
    doc = _read_doc()
    doc[_REGISTRY_KEY] = normalize_registry(models)
    if active_model_id is not None:
        doc[_ACTIVE_KEY] = active_model_id
    _write_doc(doc, "设置文件已禁用（DEVPROMPT_SETTINGS_FILE 为空），无法写模型注册表")


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
