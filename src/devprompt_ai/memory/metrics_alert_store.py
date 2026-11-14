"""Metrics 告警持久化（SQLite）：活跃去重、冷却与恢复历史。"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from devprompt_ai.domain.obs.contract.query import AlertDraft, AlertRecord
from devprompt_ai.memory.obs_schema import METRICS_ALERTS_DDL

_BUSY_TIMEOUT_MS = 5000
_COLUMNS = (
    "alert_id, rule_id, severity, status, scope_kind, scope_key, metric, observed,"
    " threshold, message, first_seen_at, last_seen_at, resolved_at, cooldown_until,"
    " schema_version"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SQLiteAlertStore:
    def __init__(self, db_path: str, *, cooldown_s: int = 300) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._cooldown_s = max(0, cooldown_s)

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def init_schema(self) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(METRICS_ALERTS_DDL)

        await asyncio.to_thread(_run)

    async def sync_alerts(
        self, drafts: list[AlertDraft], *, scope_kind: str, scope_key: str
    ) -> None:
        """把一次评估的告警集合同步到该 scope：新增/更新活跃项，缺失项置 resolved。"""
        now = _now()
        cooldown_until = (
            datetime.now(timezone.utc) + timedelta(seconds=self._cooldown_s)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(METRICS_ALERTS_DDL)
                # 立即取写锁：并发同 scope 评估时，读-判-写必须整体串行，
                # 否则两个事务都读到空活跃集、双双 INSERT，撞唯一索引（D-03）。
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    f"SELECT {_COLUMNS} FROM metrics_alerts"
                    " WHERE scope_kind=? AND scope_key=? AND status='active'",
                    (scope_kind, scope_key),
                ).fetchall()
                by_key = {(row[1], row[4], row[5]): row for row in existing}
                seen: set[tuple[str, str, str]] = set()
                for draft in drafts:
                    key = (draft.rule_id, draft.scope_kind, draft.scope_key)
                    seen.add(key)
                    row = by_key.get(key)
                    if row is None:
                        conn.execute(
                            f"INSERT INTO metrics_alerts ({_COLUMNS})"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                uuid.uuid4().hex,
                                draft.rule_id,
                                draft.severity,
                                "active",
                                draft.scope_kind,
                                draft.scope_key,
                                draft.metric,
                                float(draft.observed),
                                float(draft.threshold),
                                draft.message,
                                now,
                                now,
                                "",
                                cooldown_until,
                                1,
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE metrics_alerts SET severity=?, observed=?, threshold=?,"
                            " message=?, last_seen_at=?, cooldown_until=?"
                            " WHERE alert_id=?",
                            (
                                draft.severity,
                                float(draft.observed),
                                float(draft.threshold),
                                draft.message,
                                now,
                                cooldown_until,
                                row[0],
                            ),
                        )
                for key, row in by_key.items():
                    if key in seen:
                        continue
                    conn.execute(
                        "UPDATE metrics_alerts SET status='resolved', resolved_at=?,"
                        " last_seen_at=? WHERE alert_id=?",
                        (now, now, row[0]),
                    )
                conn.commit()

        await asyncio.to_thread(_run)

    async def list_alerts(
        self, *, status: str = "", limit: int = 50, offset: int = 0
    ) -> list[AlertRecord]:
        def _run() -> list[AlertRecord]:
            with self._connect() as conn:
                conn.executescript(METRICS_ALERTS_DDL)
                sql = f"SELECT {_COLUMNS} FROM metrics_alerts"
                params: list[Any] = []
                if status:
                    sql += " WHERE status=?"
                    params.append(status)
                sql += " ORDER BY last_seen_at DESC LIMIT ? OFFSET ?"
                params.extend([max(1, limit), max(0, offset)])
                rows = conn.execute(sql, tuple(params)).fetchall()
            return [_record(row) for row in rows]

        return await asyncio.to_thread(_run)


def _record(row: tuple[Any, ...]) -> AlertRecord:
    return AlertRecord(
        alert_id=str(row[0]),
        rule_id=str(row[1]),
        severity=str(row[2]),
        status=str(row[3]),
        scope_kind=str(row[4]),
        scope_key=str(row[5]),
        metric=str(row[6]),
        observed=float(row[7]),
        threshold=float(row[8]),
        message=str(row[9]),
        first_seen_at=str(row[10]),
        last_seen_at=str(row[11]),
        resolved_at=str(row[12] or ""),
        cooldown_until=str(row[13] or ""),
        schema_version=int(row[14]),
    )
