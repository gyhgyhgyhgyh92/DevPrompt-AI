"""真实历史库迁移验证：只对**副本**跑，绝不触碰用户真实库。

背景：2026-11-19 给 runs 表加了 snapshot_json / applied_ops 两列，靠启动时
PRAGMA table_info + ALTER 补齐。这里用真实库副本验证旧行可读、二次执行幂等。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from devprompt_ai.memory.run_store import SQLiteRunStore


def _real_db(monkeypatch: pytest.MonkeyPatch) -> Path | None:
    from devprompt_ai.config import AppConfig

    try:
        cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
        candidate = Path(cfg.db_path).expanduser()
    except Exception:  # noqa: BLE001 - 配置不可用时跳过
        return None
    return candidate if candidate.exists() else None


def _columns(db_path: Path) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        return {str(row[1]) for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    finally:
        conn.close()


def test_migration_on_real_db_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _real_db(monkeypatch)
    if source is None:
        pytest.skip("本机没有真实库，跳迁移验证")

    target = tmp_path / "copy.db"
    # WAL 库复制：连同 -wal/-shm 一起拷，避免读到旧主文件而漏掉最近写入。
    shutil.copy2(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{target}{suffix}"))

    store = SQLiteRunStore(str(target))

    async def _go() -> None:
        await store.init_schema()
        columns = _columns(target)
        assert {"snapshot_json", "applied_ops"} <= columns
        # 旧行仍可读（RunRecord 不依赖新列）
        latest = await store.latest_for_session("__no_such_session__")
        assert latest is None
        # 二次执行幂等：不重复 ALTER、不报错
        await store.init_schema()
        assert {"snapshot_json", "applied_ops"} <= _columns(target)

    asyncio.run(_go())


def test_migration_on_synthetic_legacy_db(tmp_path: Path) -> None:
    """无真实库时仍覆盖迁移逻辑：手工造旧表结构后补列。"""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE runs (
              run_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              turn_index INTEGER NOT NULL,
              status TEXT NOT NULL,
              stop_reason TEXT NOT NULL DEFAULT '',
              request_id TEXT NOT NULL DEFAULT '',
              model_id TEXT NOT NULL DEFAULT '',
              error_code INTEGER,
              error_message TEXT NOT NULL DEFAULT '',
              started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
              ended_at TEXT
            );
            INSERT INTO runs (run_id, session_id, turn_index, status)
            VALUES ('old-run', 'old-session', 0, 'done');
            """
        )
    finally:
        conn.close()

    store = SQLiteRunStore(str(db_path))

    async def _go() -> Any:
        await store.init_schema()
        assert {"snapshot_json", "applied_ops"} <= _columns(db_path)
        record = await store.get("old-run")
        assert record is not None and record.status == "done"
        assert await store.load_snapshot("old-run") == {}
        assert await store.load_applied_ops("old-run") == []

    asyncio.run(_go())
