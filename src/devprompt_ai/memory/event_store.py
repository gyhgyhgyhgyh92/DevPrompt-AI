"""会话事件存储（SQLite）：seq 事务内分配 + 增量重放。

为什么落库而非纯内存环：多端重连与进程重启都要能恢复；内存环只做读加速。
sqlite3 是同步 API，统一经 ``asyncio.to_thread`` 包装（MUST-13）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from devprompt_ai.common.hashing import sha256_hex
from devprompt_ai.domain.events import RunEvent
from devprompt_ai.memory.schema import RUN_EVENTS_DDL

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000
_DEFAULT_LIMIT = 500


def _event_checksum(session_id: str, seq: int, event_type: str, body: str) -> str:
    """事件完整性校验和：任何一列被篡改或截断都能在启动时发现。"""
    return sha256_hex(f"{session_id}|{seq}|{event_type}|{body}")


class SQLiteEventStore:
    """每操作独立连接；append 用 BEGIN IMMEDIATE 保证 seq 连续。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def verify_checksums(self, *, limit: int = 50) -> int:
        """启动校验：复核已写 checksum 的事件行，返回不匹配数量（旧库空 checksum 跳过）。

        只告警不删改——重放按 seq 语义进行，缺行由调用方按「未覆盖」披露（MUST-11d）。
        """

        def _run() -> int:
            mismatched: list[int] = []
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT session_id, seq, type, payload, checksum FROM run_events"
                    " WHERE checksum != ''"
                ).fetchall()
            for session_id, seq, event_type, body, checksum in rows:
                expected = _event_checksum(str(session_id), int(seq), str(event_type), str(body))
                if expected != checksum:
                    mismatched.append(int(seq))
                    if len(mismatched) >= limit:
                        break
            if mismatched:
                logger.warning(
                    "events.checksum_mismatch",
                    extra={"count": len(mismatched), "seqs": mismatched[:limit]},
                )
            return len(mismatched)

        return await asyncio.to_thread(_run)

    async def init_schema(self) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(RUN_EVENTS_DDL)
                # 旧库升级：checksum 列后加（CREATE TABLE IF NOT EXISTS 不会补列）
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(run_events)").fetchall()
                }
                if "checksum" not in columns:
                    conn.execute(
                        "ALTER TABLE run_events ADD COLUMN checksum TEXT NOT NULL DEFAULT ''"
                    )

        await asyncio.to_thread(_run)

    async def append(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        run_id: str = "",
    ) -> RunEvent:
        body = json.dumps(payload or {}, ensure_ascii=False)

        def _run() -> RunEvent:
            with self._connect() as conn:
                conn.executescript(RUN_EVENTS_DDL)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    seq = int(row[0]) if row else 1
                    conn.execute(
                        "INSERT INTO run_events (session_id, seq, run_id, type, payload, checksum)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            seq,
                            run_id,
                            event_type,
                            body,
                            _event_checksum(session_id, seq, event_type, body),
                        ),
                    )
                    created = conn.execute(
                        "SELECT created_at FROM run_events WHERE session_id = ? AND seq = ?",
                        (session_id, seq),
                    ).fetchone()
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            return RunEvent(
                session_id=session_id,
                seq=seq,
                type=event_type,
                payload=payload or {},
                run_id=run_id,
                created_at=str(created[0]) if created else "",
            )

        return await asyncio.to_thread(_run)

    async def since(
        self, session_id: str, seq: int, *, limit: int = _DEFAULT_LIMIT
    ) -> list[RunEvent]:
        """返回 seq 之后的事件（升序）；limit 截断用于流式分页。"""

        def _run() -> list[RunEvent]:
            with self._connect() as conn:
                conn.executescript(RUN_EVENTS_DDL)
                rows = conn.execute(
                    "SELECT session_id, seq, type, payload, run_id, created_at"
                    " FROM run_events WHERE session_id = ? AND seq > ?"
                    " ORDER BY seq ASC LIMIT ?",
                    (session_id, seq, limit),
                ).fetchall()
            return [_row_to_event(row) for row in rows]

        return await asyncio.to_thread(_run)

    async def before(
        self, session_id: str, seq: int, *, limit: int = _DEFAULT_LIMIT
    ) -> list[RunEvent]:
        """返回 seq 之前的事件（倒序取最近 limit 条，再翻正）——冷启动回填用。"""

        def _run() -> list[RunEvent]:
            with self._connect() as conn:
                conn.executescript(RUN_EVENTS_DDL)
                rows = conn.execute(
                    "SELECT session_id, seq, type, payload, run_id, created_at"
                    " FROM run_events WHERE session_id = ? AND seq < ?"
                    " ORDER BY seq DESC LIMIT ?",
                    (session_id, seq, limit),
                ).fetchall()
            return [_row_to_event(row) for row in reversed(rows)]

        return await asyncio.to_thread(_run)

    async def last_seq(self, session_id: str) -> int:
        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(RUN_EVENTS_DDL)
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return int(row[0]) if row else 0

        return await asyncio.to_thread(_run)


def _row_to_event(row: tuple[Any, ...]) -> RunEvent:
    session_id, seq, event_type, payload, run_id, created_at = row
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        data = {}
    return RunEvent(
        session_id=str(session_id),
        seq=int(seq),
        type=str(event_type),
        payload=data if isinstance(data, dict) else {},
        run_id=str(run_id or ""),
        created_at=str(created_at or ""),
    )
