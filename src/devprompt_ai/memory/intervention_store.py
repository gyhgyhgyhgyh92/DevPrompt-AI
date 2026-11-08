"""干预记录存储（SQLite）：pending 注册与「第一应答获胜」。

条件更新 `WHERE status='pending'` 是唯一裁决点：第二个客户端的应答返回 False，
API 层据此回 404/409，不会出现「两个端各选一个答案」。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, cast

from devprompt_ai.domain.interventions import (
    VALID_DECISIONS,
    Intervention,
    InterventionKind,
    InterventionStatus,
)
from devprompt_ai.memory.schema import INTERVENTIONS_DDL

_BUSY_TIMEOUT_MS = 5000

_COLUMNS = (
    "request_id, session_id, run_id, kind, payload, status, decision, answer,"
    " created_at, resolved_at"
)


class SQLiteInterventionStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def register(
        self,
        session_id: str,
        *,
        run_id: str = "",
        kind: InterventionKind = "question",
        payload: dict[str, Any] | None = None,
    ) -> Intervention:
        request_id = uuid.uuid4().hex
        body = json.dumps(payload or {}, ensure_ascii=False)

        def _run() -> Intervention:
            with self._connect() as conn:
                conn.executescript(INTERVENTIONS_DDL)
                conn.execute(
                    "INSERT INTO interventions (request_id, session_id, run_id, kind, payload)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (request_id, session_id, run_id, kind, body),
                )
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM interventions WHERE request_id = ?",  # noqa: S608
                    (request_id,),
                ).fetchone()
            return _row_to_intervention(row) if row else _fallback(request_id, session_id)

        return await asyncio.to_thread(_run)

    async def resolve(self, request_id: str, decision: str, answer: str = "") -> bool:
        """返回是否由本次调用裁决成功；已裁决或不存在返回 False。"""
        if decision not in VALID_DECISIONS:
            raise ValueError(f"非法裁决：{decision!r}")

        def _run() -> bool:
            with self._connect() as conn:
                conn.executescript(INTERVENTIONS_DDL)
                cursor = conn.execute(
                    "UPDATE interventions SET status = 'resolved', decision = ?, answer = ?,"
                    " resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                    " WHERE request_id = ? AND status = 'pending'",
                    (decision, answer, request_id),
                )
                return (cursor.rowcount or 0) > 0

        return await asyncio.to_thread(_run)

    async def get(self, request_id: str) -> Intervention | None:
        def _run() -> Intervention | None:
            with self._connect() as conn:
                conn.executescript(INTERVENTIONS_DDL)
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM interventions WHERE request_id = ?",  # noqa: S608
                    (request_id,),
                ).fetchone()
            return _row_to_intervention(row) if row else None

        return await asyncio.to_thread(_run)

    async def pending(self, session_id: str) -> list[Intervention]:
        def _run() -> list[Intervention]:
            with self._connect() as conn:
                conn.executescript(INTERVENTIONS_DDL)
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM interventions"  # noqa: S608
                    " WHERE session_id = ? AND status = 'pending' ORDER BY created_at ASC",
                    (session_id,),
                ).fetchall()
            return [_row_to_intervention(row) for row in rows]

        return await asyncio.to_thread(_run)

    async def cancel_pending(self, session_id: str) -> int:
        """会话中止/结束时清场：未裁决的置 cancelled，避免永远挂起。"""

        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(INTERVENTIONS_DDL)
                cursor = conn.execute(
                    "UPDATE interventions SET status = 'cancelled',"
                    " resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                    " WHERE session_id = ? AND status = 'pending'",
                    (session_id,),
                )
                return int(cursor.rowcount or 0)

        return await asyncio.to_thread(_run)


def _row_to_intervention(row: tuple[Any, ...]) -> Intervention:
    request_id, session_id, run_id, kind, payload, status, decision, answer, created, resolved = row
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        data = {}
    return Intervention(
        request_id=str(request_id),
        session_id=str(session_id),
        run_id=str(run_id or ""),
        kind=cast(InterventionKind, str(kind)),
        payload=data if isinstance(data, dict) else {},
        status=cast(InterventionStatus, str(status)),
        decision=str(decision or ""),
        answer=str(answer or ""),
        created_at=str(created or ""),
        resolved_at=str(resolved) if resolved else None,
    )


def _fallback(request_id: str, session_id: str) -> Intervention:
    return Intervention(
        request_id=request_id,
        session_id=session_id,
        run_id="",
        kind="question",
        status="pending",
    )
