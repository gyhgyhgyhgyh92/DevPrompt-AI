"""模型路由统计（SQLite）：bandit 的胜率与延迟来源。

只记聚合计数，不记原句、不记请求内容（MUST-19）。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from devprompt_ai.memory.schema import ROUTING_STATS_DDL

_BUSY_TIMEOUT_MS = 5000


class SQLiteRoutingStats:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def record(
        self,
        *,
        model_id: str,
        task_kind: str,
        success: bool,
        latency_ms: int,
    ) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(ROUTING_STATS_DDL)
                conn.execute(
                    "INSERT INTO routing_stats (model_id, task_kind, attempts, successes,"
                    " total_latency_ms) VALUES (?, ?, 1, ?, ?)"
                    " ON CONFLICT(model_id, task_kind) DO UPDATE SET"
                    " attempts = attempts + 1,"
                    " successes = successes + excluded.successes,"
                    " total_latency_ms = total_latency_ms + excluded.total_latency_ms,"
                    " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (model_id, task_kind, 1 if success else 0, max(0, latency_ms)),
                )

        await asyncio.to_thread(_run)

    async def load_all(self) -> dict[tuple[str, str], tuple[int, int, int]]:
        """返回 {(model_id, task_kind): (attempts, successes, total_latency_ms)}。"""

        def _run() -> dict[tuple[str, str], tuple[int, int, int]]:
            with self._connect() as conn:
                conn.executescript(ROUTING_STATS_DDL)
                rows = conn.execute(
                    "SELECT model_id, task_kind, attempts, successes, total_latency_ms"
                    " FROM routing_stats"
                ).fetchall()
            return {
                (str(model), str(kind)): (int(attempts), int(successes), int(latency))
                for model, kind, attempts, successes, latency in rows
            }

        return await asyncio.to_thread(_run)
