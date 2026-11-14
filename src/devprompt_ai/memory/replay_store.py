"""Replay 任务与节点结果持久化（SQLite）。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from devprompt_ai.domain.obs.contract.query import ReplayNodeResult, ReplayRunRecord
from devprompt_ai.memory.obs_schema import REPLAY_DDL

_BUSY_TIMEOUT_MS = 5000


class SQLiteReplayStore:
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
                conn.executescript(REPLAY_DDL)

        await asyncio.to_thread(_run)

    async def create_run(self, record: ReplayRunRecord, nodes: list[ReplayNodeResult]) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPLAY_DDL)
                conn.execute(
                    "INSERT INTO replay_runs (run_id, mode, status, left_trace_id,"
                    " right_trace_id, matched_nodes, mismatched_nodes, missing_nodes,"
                    " result_json, error_json, created_at, ended_at, schema_version)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.run_id,
                        record.mode,
                        record.status,
                        record.left_trace_id,
                        record.right_trace_id,
                        record.matched_nodes,
                        record.mismatched_nodes,
                        record.missing_nodes,
                        json.dumps(record.result, ensure_ascii=False),
                        json.dumps(record.error, ensure_ascii=False),
                        record.created_at,
                        record.ended_at,
                        record.schema_version,
                    ),
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO replay_nodes (run_id, seq, kind, name, match,"
                    " expected_json, actual_json, diff_json) VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (
                            record.run_id,
                            node.seq,
                            node.kind,
                            node.name,
                            1 if node.match else 0,
                            json.dumps(node.expected, ensure_ascii=False),
                            json.dumps(node.actual, ensure_ascii=False),
                            json.dumps(node.diff, ensure_ascii=False),
                        )
                        for node in nodes
                    ],
                )
                conn.commit()

        await asyncio.to_thread(_run)

    async def save_nodes(self, run_id: str, nodes: list[ReplayNodeResult]) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPLAY_DDL)
                conn.execute("DELETE FROM replay_nodes WHERE run_id=?", (run_id,))
                conn.executemany(
                    "INSERT OR REPLACE INTO replay_nodes (run_id, seq, kind, name, match,"
                    " expected_json, actual_json, diff_json) VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (
                            run_id,
                            node.seq,
                            node.kind,
                            node.name,
                            1 if node.match else 0,
                            json.dumps(node.expected, ensure_ascii=False),
                            json.dumps(node.actual, ensure_ascii=False),
                            json.dumps(node.diff, ensure_ascii=False),
                        )
                        for node in nodes
                    ],
                )
                conn.commit()

        await asyncio.to_thread(_run)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        matched: int,
        mismatched: int,
        missing: int,
        result: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPLAY_DDL)
                conn.execute(
                    "UPDATE replay_runs SET status=?, matched_nodes=?, mismatched_nodes=?,"
                    " missing_nodes=?, result_json=?, error_json=?,"
                    " ended_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE run_id=?",
                    (
                        status,
                        matched,
                        mismatched,
                        missing,
                        json.dumps(result, ensure_ascii=False),
                        json.dumps(error or {}, ensure_ascii=False),
                        run_id,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_run)

    async def get_run(self, run_id: str) -> ReplayRunRecord | None:
        def _run() -> ReplayRunRecord | None:
            with self._connect() as conn:
                conn.executescript(REPLAY_DDL)
                row = conn.execute(
                    "SELECT run_id, mode, status, left_trace_id, right_trace_id,"
                    " matched_nodes, mismatched_nodes, missing_nodes, result_json,"
                    " error_json, created_at, ended_at, schema_version"
                    " FROM replay_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            if row is None:
                return None
            return ReplayRunRecord(
                run_id=str(row[0]),
                mode=str(row[1]),
                status=str(row[2]),
                left_trace_id=str(row[3]),
                right_trace_id=str(row[4] or ""),
                matched_nodes=int(row[5]),
                mismatched_nodes=int(row[6]),
                missing_nodes=int(row[7]),
                result=_loads(row[8]),
                error=_loads(row[9]),
                created_at=str(row[10]),
                ended_at=str(row[11] or ""),
                schema_version=int(row[12]),
            )

        return await asyncio.to_thread(_run)

    async def list_nodes(self, run_id: str) -> list[ReplayNodeResult]:
        def _run() -> list[ReplayNodeResult]:
            with self._connect() as conn:
                conn.executescript(REPLAY_DDL)
                rows = conn.execute(
                    "SELECT seq, kind, name, match, expected_json, actual_json, diff_json"
                    " FROM replay_nodes WHERE run_id=? ORDER BY seq ASC",
                    (run_id,),
                ).fetchall()
            return [
                ReplayNodeResult(
                    seq=int(row[0]),
                    kind=str(row[1]),
                    name=str(row[2]),
                    match=bool(row[3]),
                    expected=_loads(row[4]),
                    actual=_loads(row[5]),
                    diff=_loads(row[6]),
                )
                for row in rows
            ]

        return await asyncio.to_thread(_run)


def _loads(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
