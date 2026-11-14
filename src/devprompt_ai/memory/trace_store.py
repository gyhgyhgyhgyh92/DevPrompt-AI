"""Trace 存储（SQLite）：完整事件落库、调用链查询与会话级聚合。

SQL 只在本模块出现（MUST-06）；三模块通过 ``TraceStore/TraceReader`` 端口访问。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from devprompt_ai.domain.obs.contract.query import AggregateQuery, MetricSeries, TraceQuery
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceSummary
from devprompt_ai.domain.obs.metrics.aggregate import build_series, rows_from_dicts
from devprompt_ai.memory.obs_schema import TRACE_EVENTS_DDL

_COLUMNS = (
    "trace_id, seq, event_id, session_id, turn_id, turn_index, run_id, parent_id,"
    " kind, name, status, started_at, ended_at, duration_ms, input_json, output_json,"
    " error_json, attributes_json, schema_version"
)
_BUSY_TIMEOUT_MS = 5000
_MAX_ROWS = 50000


class SQLiteTraceStore:
    """每操作独立连接；批量写入在一个事务内完成。"""

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
                conn.executescript(TRACE_EVENTS_DDL)

        await asyncio.to_thread(_run)

    async def append_events(self, events: list[TraceEvent]) -> None:
        if not events:
            return
        rows = [event.to_row() for event in events]

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.executemany(
                        f"INSERT OR REPLACE INTO trace_events ({_COLUMNS})"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        rows,
                    )
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise

        await asyncio.to_thread(_run)

    async def list_traces(self, session_id: str, *, limit: int = 200) -> list[TraceSummary]:
        def _run() -> list[TraceSummary]:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                rows = conn.execute(
                    "SELECT trace_id, session_id,"
                    " MAX(CASE WHEN kind='turn.start' THEN turn_id END) AS turn_id,"
                    " MIN(turn_index), MIN(started_at), MAX(ended_at), COUNT(*),"
                    " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),"
                    " SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END),"
                    " MAX(CASE WHEN kind='turn.start' THEN"
                    " json_extract(attributes_json,'$.input_hash') END)"
                    " FROM trace_events WHERE session_id = ? GROUP BY trace_id"
                    " ORDER BY MIN(turn_index) ASC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            out: list[TraceSummary] = []
            for row in rows:
                failed = int(row[7] or 0)
                partial = int(row[8] or 0)
                out.append(
                    TraceSummary(
                        trace_id=str(row[0]),
                        session_id=str(row[1]),
                        turn_id=str(row[2] or ""),
                        turn_index=int(row[3] or 0),
                        started_at=str(row[4] or ""),
                        ended_at=str(row[5] or ""),
                        event_count=int(row[6] or 0),
                        failed_count=failed,
                        input_hash=str(row[9] or ""),
                        status="failed" if failed else ("partial" if partial else "ok"),
                    )
                )
            return out

        return await asyncio.to_thread(_run)

    async def query_events(self, query: TraceQuery) -> tuple[list[TraceEvent], bool, int]:
        clauses: list[str] = []
        params: list[Any] = []
        if query.session_id:
            clauses.append("session_id = ?")
            params.append(query.session_id)
        if query.trace_id:
            clauses.append("trace_id = ?")
            params.append(query.trace_id)
        if query.kind:
            clauses.append("kind = ?")
            params.append(query.kind)
        if query.from_ts:
            clauses.append("started_at >= ?")
            params.append(query.from_ts)
        if query.to_ts:
            clauses.append("started_at <= ?")
            params.append(query.to_ts)
        # cursor 是「已读行偏移」而非 seq：seq 按 trace 独立编号，多轮时用 seq 过滤会
        # 交错并漏掉后续 trace 的小 seq 事件（2026-11-14 D-01）。
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {_COLUMNS} FROM trace_events{where}"
            " ORDER BY turn_index ASC, started_at ASC, trace_id ASC, seq ASC LIMIT ? OFFSET ?"
        )
        params.append(max(1, query.limit) + 1)
        params.append(max(0, query.cursor))

        def _run() -> tuple[list[TraceEvent], bool, int]:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                rows = conn.execute(sql, tuple(params)).fetchall()
            has_more = len(rows) > query.limit
            kept = rows[: query.limit]
            events = [TraceEvent.from_row(row) for row in kept]
            next_cursor = query.cursor + len(events) if has_more and events else 0
            return events, has_more, next_cursor

        return await asyncio.to_thread(_run)

    async def trace_summary(self, trace_id: str) -> TraceSummary | None:
        def _run() -> TraceSummary | None:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                row = conn.execute(
                    "SELECT trace_id, session_id,"
                    " MAX(CASE WHEN kind='turn.start' THEN turn_id END),"
                    " MIN(turn_index), MIN(started_at), MAX(ended_at), COUNT(*),"
                    " SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),"
                    " SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END),"
                    " MAX(CASE WHEN kind='turn.start' THEN"
                    " json_extract(attributes_json,'$.input_hash') END)"
                    " FROM trace_events WHERE trace_id=? GROUP BY trace_id",
                    (trace_id,),
                ).fetchone()
            if row is None:
                return None
            failed = int(row[7] or 0)
            partial = int(row[8] or 0)
            return TraceSummary(
                trace_id=str(row[0]),
                session_id=str(row[1]),
                turn_id=str(row[2] or ""),
                turn_index=int(row[3] or 0),
                started_at=str(row[4] or ""),
                ended_at=str(row[5] or ""),
                event_count=int(row[6] or 0),
                failed_count=failed,
                input_hash=str(row[9] or ""),
                status="failed" if failed else ("partial" if partial else "ok"),
            )

        return await asyncio.to_thread(_run)

    async def list_trace_events(self, trace_id: str) -> list[TraceEvent]:
        def _run() -> list[TraceEvent]:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM trace_events WHERE trace_id = ? ORDER BY seq ASC",
                    (trace_id,),
                ).fetchall()
            return [TraceEvent.from_row(row) for row in rows]

        return await asyncio.to_thread(_run)

    async def get_event(self, event_id: str) -> TraceEvent | None:
        def _run() -> TraceEvent | None:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM trace_events WHERE event_id = ? LIMIT 1",
                    (event_id,),
                ).fetchone()
            return TraceEvent.from_row(row) if row is not None else None

        return await asyncio.to_thread(_run)

    async def aggregate(self, query: AggregateQuery) -> list[MetricSeries]:
        clauses: list[str] = []
        params: list[Any] = []
        if query.session_id:
            clauses.append("session_id = ?")
            params.append(query.session_id)
        if query.trace_id:
            clauses.append("trace_id = ?")
            params.append(query.trace_id)
        if query.from_ts:
            clauses.append("started_at >= ?")
            params.append(query.from_ts)
        if query.to_ts:
            clauses.append("started_at <= ?")
            params.append(query.to_ts)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT kind, name, status, turn_index, duration_ms, started_at,"
            " COALESCE(json_extract(attributes_json,'$.model_id'),''),"
            " COALESCE(json_extract(attributes_json,'$.tokens'),0)"
            f" FROM trace_events{where} ORDER BY started_at ASC LIMIT {_MAX_ROWS}"
        )

        def _run() -> list[MetricSeries]:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                rows = conn.execute(sql, tuple(params)).fetchall()
            items = [
                {
                    "kind": row[0],
                    "name": row[1],
                    "status": row[2],
                    "turn_index": row[3],
                    "duration_ms": row[4],
                    "started_at": row[5],
                    "model_id": row[6],
                    "tokens": row[7],
                }
                for row in rows
            ]
            return build_series(
                rows_from_dicts(items),
                dimension=query.group_by,
                bucket=query.bucket,
                percentiles=query.percentiles,
                limit=query.limit,
            )

        return await asyncio.to_thread(_run)

    async def last_seq(self, trace_id: str) -> int:
        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM trace_events WHERE trace_id = ?",
                    (trace_id,),
                ).fetchone()
            return int(row[0]) if row else 0

        return await asyncio.to_thread(_run)

    async def cleanup_expired(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

        def _run() -> int:
            with self._connect() as conn:
                conn.executescript(TRACE_EVENTS_DDL)
                cursor = conn.execute("DELETE FROM trace_events WHERE started_at < ?", (cutoff,))
                conn.commit()
            return int(cursor.rowcount or 0)

        return await asyncio.to_thread(_run)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
