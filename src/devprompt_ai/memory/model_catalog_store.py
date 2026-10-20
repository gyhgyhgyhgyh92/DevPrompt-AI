"""模型目录持久化（2026-10-17 动态模型目录）。

**为什么落库**：模型清单是刷新时拉来的网络数据，但「拉不到就清空」不可接受——
限流或端点抖动不该让用户失去已配好的模型。因此最近一次成功结果落库，
刷新失败时读它兜底（service 层把失败原因作为 ``warning`` 一起返回）。

**边界**：
- SQL 只出现在本文件与 `schema.py`（MUST-06）；
- 表结构**无密钥列**，api_key 只在内存中用于请求（MUST-19）；
- 同步 sqlite3 调用由调用方用 `asyncio.to_thread` 包装（MUST-13）。

测试隔离：沿用 ``DEVPROMPT_SETTINGS_DB`` 环境变量（与 settings_store 同一路径）。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from devprompt_ai.domain.model_catalog.catalog import ModelCatalogItem
from devprompt_ai.memory.schema import MODEL_CATALOG_DDL

_DEFAULT_DB = "~/.devprompt-ai/devprompt.db"
_BUSY_TIMEOUT_MS = 5000


class ModelCatalogStoreError(RuntimeError):
    """模型目录落库失败（库被禁用 / 磁盘不可写）。"""


def _db_path() -> Path | None:
    raw = os.environ.get("DEVPROMPT_SETTINGS_DB", _DEFAULT_DB)
    return Path(raw).expanduser() if raw else None


def _row_to_items(payload: str | None) -> list[ModelCatalogItem]:
    """payload_json → 条目列表；损坏静默返回空（由上层回落静态表）。"""
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[ModelCatalogItem] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id") or "").strip()
        if not model_id:
            continue
        window = entry.get("max_context_length")
        tiers = entry.get("context_window_tiers")
        efforts = entry.get("reasoning_efforts")
        items.append(
            ModelCatalogItem(
                model_id=model_id,
                label=str(entry.get("label") or model_id),
                max_context_length=window if isinstance(window, int) and window > 0 else None,
                context_window_tiers=tuple(
                    int(t) for t in (tiers if isinstance(tiers, list) else []) if isinstance(t, int)
                ),
                reasoning_efforts=tuple(
                    str(e) for e in (efforts if isinstance(efforts, list) else []) if str(e).strip()
                ),
                default_effort=str(entry.get("default_effort") or ""),
                source="remote" if entry.get("source") == "remote" else "static",
            )
        )
    return items


def read_model_catalog(
    provider_key: str, base_url: str
) -> tuple[list[ModelCatalogItem], str | None]:
    """读该厂商最近一次拉取结果。

    :returns: ``(条目列表, 拉取时间 ISO 串)``；**无记录时返回 ``([], None)``** 而非报错——
        「还没刷新过」是正常状态，不是故障。
    """
    path = _db_path()
    if path is None or not path.exists():
        return [], None
    try:
        conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
        try:
            row = conn.execute(
                "SELECT payload_json, fetched_at FROM model_catalog"
                " WHERE provider_key = ? AND base_url = ?",
                (provider_key, base_url),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return [], None
    if row is None:
        return [], None
    return _row_to_items(str(row[0])), str(row[1])


def write_model_catalog(provider_key: str, base_url: str, items: list[ModelCatalogItem]) -> str:
    """upsert 该厂商的目录快照，返回写入时间（ISO 串）。"""
    path = _db_path()
    if path is None:
        raise ModelCatalogStoreError("设置库已禁用（DEVPROMPT_SETTINGS_DB 为空），无法保存模型列表")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [
            {
                "model_id": item.model_id,
                "label": item.label,
                "max_context_length": item.max_context_length,
                "context_window_tiers": list(item.context_window_tiers),
                "reasoning_efforts": list(item.reasoning_efforts),
                "default_effort": item.default_effort,
                "source": item.source,
            }
            for item in items
        ],
        ensure_ascii=False,
    )

    def _run() -> str:
        conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000)
        try:
            conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            conn.executescript(MODEL_CATALOG_DDL)
            conn.execute(
                "INSERT INTO model_catalog (provider_key, base_url, payload_json)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(provider_key, base_url) DO UPDATE SET"
                " payload_json = excluded.payload_json,"
                " fetched_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (provider_key, base_url, payload),
            )
            conn.commit()
            row = conn.execute(
                "SELECT fetched_at FROM model_catalog WHERE provider_key = ? AND base_url = ?",
                (provider_key, base_url),
            ).fetchone()
        finally:
            conn.close()
        return str(row[0]) if row else ""

    try:
        return _run()
    except sqlite3.Error as exc:
        raise ModelCatalogStoreError(f"模型列表写入失败：{exc}") from exc


def catalog_db_enabled() -> bool:
    """目录库是否可用（供 /health 提示，不抛异常）。"""
    return _db_path() is not None
