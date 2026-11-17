"""运行记录存储（SQLite）：创建 / 推进状态 / 查询。

执行体与 HTTP 连接解耦后，本表只由执行器写；连接侧只读。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, cast

from devprompt_ai.domain.runs import TERMINAL_RUN_STATUSES, RunRecord, RunStatus
from devprompt_ai.memory.schema import RUNS_DDL

_BUSY_TIMEOUT_MS = 5000

_COLUMNS = (
    "run_id, session_id, turn_index, status, stop_reason, request_id, model_id,"
    " error_code, error_message, started_at, ended_at"
)


class SQLiteRunStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def init_schema(self) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(RUNS_DDL)

        await asyncio.to_thread(_run)

    async def create(
        self,
        *,
        run_id: str,
        session_id: str,
        turn_index: int,
        request_id: str = "",
        model_id: str = "",
    ) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                conn.execute(
                    "INSERT INTO runs"
                    " (run_id, session_id, turn_index, status, request_id, model_id)"
                    " VALUES (?, ?, ?, 'running', ?, ?)",
                    (run_id, session_id, turn_index, request_id, model_id),
                )

        await asyncio.to_thread(_run)

    async def finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        stop_reason: str = "",
        error_code: int | None = None,
        error_message: str = "",
    ) -> None:
        """推进到终态；非终态传入时忽略（调用方错误不应污染记录）。"""
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError(f"finish 只接受终态：{status!r}")

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                conn.execute(
                    "UPDATE runs SET status = ?, stop_reason = ?, error_code = ?,"
                    " error_message = ?, ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                    " WHERE run_id = ?",
                    (status, stop_reason, error_code, error_message, run_id),
                )

        await asyncio.to_thread(_run)

    async def get(self, run_id: str) -> RunRecord | None:
        def _run() -> RunRecord | None:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM runs WHERE run_id = ?",  # noqa: S608 - 常量列名
                    (run_id,),
                ).fetchone()
            return _row_to_run(row) if row else None

        return await asyncio.to_thread(_run)

    async def latest_for_session(self, session_id: str) -> RunRecord | None:
        def _run() -> RunRecord | None:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM runs WHERE session_id = ?"  # noqa: S608
                    " ORDER BY started_at DESC, rowid DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            return _row_to_run(row) if row else None

        return await asyncio.to_thread(_run)

    async def mark_orphans_aborted(self, older_than_minutes: int = 30) -> int:
        """启动自愈：把崩溃遗留的 running 置 ABORTED（不误杀刚启动的）。"""

        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                cursor = conn.execute(
                    "UPDATE runs SET status = 'aborted', stop_reason = 'process-restart',"
                    " ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                    " WHERE status IN ('queued','running')"
                    " AND started_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)",
                    (f"-{max(1, older_than_minutes)} minutes",),
                )
                return int(cursor.rowcount or 0)

        return await asyncio.to_thread(_run)


def _row_to_run(row: tuple[Any, ...]) -> RunRecord:
    (
        run_id,
        session_id,
        turn_index,
        status,
        stop_reason,
        request_id,
        model_id,
        error_code,
        error_message,
        started_at,
        ended_at,
    ) = row
    return RunRecord(
        run_id=str(run_id),
        session_id=str(session_id),
        turn_index=int(turn_index),
        status=cast(RunStatus, str(status)),
        stop_reason=str(stop_reason or ""),
        request_id=str(request_id or ""),
        model_id=str(model_id or ""),
        error_code=int(error_code) if error_code is not None else None,
        error_message=str(error_message or ""),
        started_at=str(started_at or ""),
        ended_at=str(ended_at) if ended_at else None,
    )
