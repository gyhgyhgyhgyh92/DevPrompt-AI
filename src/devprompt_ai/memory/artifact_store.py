"""工件存储（SQLite）：被压缩丢弃的历史段与工具全量输出。

内容可能含用户原句与代码正文，只落本地库、只在显式回读时取出；
**禁止**把 content 写入日志或 API 错误响应（MUST-19）。

状态：压缩走内存折叠、工具输出走 output_store 文件方案，业主裁定（2026-11-08）
不需要消费方，维持单测覆盖不接线。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from devprompt_ai.memory.schema import ARTIFACTS_DDL

_BUSY_TIMEOUT_MS = 5000


class SQLiteArtifactStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def put(
        self,
        content: str,
        *,
        kind: str,
        session_id: str = "",
        run_id: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        artifact_id = uuid.uuid4().hex
        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(ARTIFACTS_DDL)
                conn.execute(
                    "INSERT INTO artifacts"
                    " (artifact_id, session_id, run_id, kind, content, meta_json)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (artifact_id, session_id, run_id, kind, content, meta_json),
                )

        await asyncio.to_thread(_run)
        return artifact_id

    async def get(self, artifact_id: str) -> str | None:
        def _run() -> str | None:
            with self._connect() as conn:
                conn.executescript(ARTIFACTS_DDL)
                row = conn.execute(
                    "SELECT content FROM artifacts WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
            return str(row[0]) if row else None

        return await asyncio.to_thread(_run)

    async def get_meta(self, artifact_id: str) -> dict[str, Any] | None:
        def _run() -> dict[str, Any] | None:
            with self._connect() as conn:
                conn.executescript(ARTIFACTS_DDL)
                row = conn.execute(
                    "SELECT meta_json FROM artifacts WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                data = {}
            return data if isinstance(data, dict) else {}

        return await asyncio.to_thread(_run)
