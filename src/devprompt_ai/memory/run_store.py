"""运行记录存储（SQLite）：创建 / 推进状态 / 查询。

执行体与 HTTP 连接解耦后，本表只由执行器写；连接侧只读。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from devprompt_ai.domain.runs import TERMINAL_RUN_STATUSES, RunRecord, RunStatus
from devprompt_ai.memory.schema import RUNS_DDL

_BUSY_TIMEOUT_MS = 5000

_COLUMNS = (
    "run_id, session_id, turn_index, status, stop_reason, request_id, model_id,"
    " error_code, error_message, started_at, ended_at, snapshot_json, applied_ops"
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
                # 旧库迁移：CREATE IF NOT EXISTS 不会补列，显式 ALTER 幂等补齐。
                existing = {
                    str(row[1]) for row in conn.execute("PRAGMA table_info(runs)").fetchall()
                }
                for column, ddl in (
                    ("snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("applied_ops", "TEXT NOT NULL DEFAULT '[]'"),
                ):
                    if column not in existing:
                        conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")

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

    async def save_snapshot(self, run_id: str, snapshot: dict[str, Any]) -> None:
        """保存断点快照（整包 session 状态 + steps）；失败只降级，不阻断执行。"""

        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE runs SET snapshot_json = ? WHERE run_id = ?",
                    (json.dumps(snapshot, ensure_ascii=False, default=str), run_id),
                )

        await asyncio.to_thread(_run)

    async def load_snapshot(self, run_id: str) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT snapshot_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            if not row or not row[0]:
                return {}
            try:
                value = json.loads(str(row[0]))
            except json.JSONDecodeError:
                return {}
            return value if isinstance(value, dict) else {}

        return await asyncio.to_thread(_run)

    async def load_applied_ops(self, run_id: str) -> list[str]:
        """已执行的副作用键（续跑幂等：同一键不重复产生副作用）。"""
        def _run() -> list[str]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT applied_ops FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            if not row or not row[0]:
                return []
            try:
                value = json.loads(str(row[0]))
            except json.JSONDecodeError:
                return []
            return [str(item) for item in value] if isinstance(value, list) else []

        return await asyncio.to_thread(_run)

    async def record_applied_op(self, run_id: str, op_key: str) -> None:
        """追加一个副作用键；同键幂等（重复写入不改变结果）。"""
        if not op_key:
            return

        def _run() -> None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT applied_ops FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                try:
                    keys = json.loads(str(row[0])) if row and row[0] else []
                except json.JSONDecodeError:
                    keys = []
                if not isinstance(keys, list):
                    keys = []
                if op_key in keys:
                    return
                keys.append(op_key)
                conn.execute(
                    "UPDATE runs SET applied_ops = ? WHERE run_id = ?",
                    (json.dumps(keys, ensure_ascii=False), run_id),
                )

        await asyncio.to_thread(_run)

    async def reopen(self, run_id: str) -> bool:
        """把崩溃/取消遗留的 run 复位为 running，供同 run_id 续跑。"""
        def _run() -> bool:
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE runs SET status = 'running', ended_at = NULL"
                    " WHERE run_id = ? AND status IN ('aborted', 'error')",
                    (run_id,),
                )
                return bool(cursor.rowcount)

        return await asyncio.to_thread(_run)

    async def mark_orphans_aborted(self, older_than_minutes: int = 30) -> int:
        """启动自愈：把崩溃遗留的 running 置 ABORTED。

        ``older_than_minutes=0`` 表示不限时间、立即收尾全部活跃 run——只在
        ``SingleWriterLock`` 已成功接管（即旧持有者确认死亡）后调用。
        """

        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(RUNS_DDL)
                cursor = conn.execute(
                    "UPDATE runs SET status = 'aborted', stop_reason = 'process-restart',"
                    " ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                    " WHERE status IN ('queued','running')"
                    " AND started_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)",
                    (f"-{older_than_minutes} minutes",),
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
        _snapshot_json,
        _applied_ops,
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
