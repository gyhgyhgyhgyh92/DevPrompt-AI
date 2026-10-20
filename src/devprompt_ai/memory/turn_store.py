"""L1 多轮 turn 存储（2026-10-20）：append-only，一行一轮。

为什么不用「session.payload 全量覆盖」：那条路每次写入都要重写全部历史，
写放大随轮数线性增长（50 轮后每轮 O(n)）；而且状态机会被迫挂在 session 上。
这里把状态机作用域下沉到 turn，session 只剩容器字段。

**并发语义**：`(session_id, turn_index)` 唯一索引承担乐观锁——重复提交在数据库层
被拒（`TurnConflictError` → 6001），不依赖前端防抖（MUST-15）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from devprompt_ai.domain.models import TurnRecord
from devprompt_ai.memory.schema import TURNS_DDL

_BUSY_TIMEOUT_MS = 5000

_COLUMNS = (
    "turn_id, session_id, turn_index, state, input, facts_json, clarifications_json, "
    "output_json, summary_json, usage_json, created_at"
)

#: 插入列不含 created_at——交给 DDL 默认值（同一时钟来源，避免 Python/SQLite 时区不一致）
_INSERT_COLUMNS = (
    "turn_id, session_id, turn_index, state, input, facts_json, clarifications_json, "
    "output_json, summary_json, usage_json"
)


class TurnConflictError(RuntimeError):
    """同一 (session_id, turn_index) 已存在：并发或重复提交。"""


def _row_to_turn(row: tuple[Any, ...]) -> TurnRecord:
    (
        turn_id,
        session_id,
        turn_index,
        state,
        input_text,
        facts_json,
        clarifications_json,
        output_json,
        summary_json,
        usage_json,
        created_at,
    ) = row
    return TurnRecord(
        turn_id=str(turn_id),
        session_id=str(session_id),
        turn_index=int(turn_index),
        state=str(state),
        input=str(input_text),
        facts=list(json.loads(facts_json or "[]")),
        clarifications=dict(json.loads(clarifications_json or "{}")),
        output=list(json.loads(output_json or "[]")),
        summary=dict(json.loads(summary_json or "{}")),
        usage=dict(json.loads(usage_json or "{}")),
        created_at=str(created_at),
    )


class SQLiteTurnStore:
    """TurnStore 的 SQLite 实现（阻塞 I/O 经 asyncio.to_thread 卸载，MUST-13）。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def append(self, turn: TurnRecord) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(TURNS_DDL)
                try:
                    conn.execute(
                        f"INSERT INTO forge_turns ({_INSERT_COLUMNS}) "  # noqa: S608 - 常量列名
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            turn.turn_id,
                            turn.session_id,
                            turn.turn_index,
                            turn.state,
                            turn.input,
                            json.dumps(turn.facts, ensure_ascii=False),
                            json.dumps(turn.clarifications, ensure_ascii=False),
                            json.dumps(turn.output, ensure_ascii=False),
                            json.dumps(turn.summary, ensure_ascii=False),
                            json.dumps(turn.usage, ensure_ascii=False),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise TurnConflictError(
                        f"turn 已存在：session={turn.session_id} index={turn.turn_index}"
                    ) from exc

        await asyncio.to_thread(_run)

    async def finish(
        self,
        turn_id: str,
        *,
        state: str,
        facts: list[dict[str, Any]],
        clarifications: dict[str, str],
        output: list[dict[str, Any]],
        summary: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """回填占位 turn 的产出（append 后只 UPDATE 一次，仍保持一轮一行）。"""

        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE forge_turns SET state=?, facts_json=?, clarifications_json=?, "
                    "output_json=?, summary_json=?, usage_json=? WHERE turn_id=?",
                    (
                        state,
                        json.dumps(facts, ensure_ascii=False),
                        json.dumps(clarifications, ensure_ascii=False),
                        json.dumps(output, ensure_ascii=False),
                        json.dumps(summary, ensure_ascii=False),
                        json.dumps(usage, ensure_ascii=False),
                        turn_id,
                    ),
                )

        await asyncio.to_thread(_run)

    async def list_for_session(self, session_id: str) -> list[TurnRecord]:
        def _run() -> list[TurnRecord]:
            with self._connect() as conn:
                conn.executescript(TURNS_DDL)
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM forge_turns WHERE session_id = ? "  # noqa: S608
                    "ORDER BY turn_index ASC",
                    (session_id,),
                ).fetchall()
            return [_row_to_turn(row) for row in rows]

        return await asyncio.to_thread(_run)

    async def load(self, turn_id: str) -> TurnRecord | None:
        def _run() -> TurnRecord | None:
            with self._connect() as conn:
                conn.executescript(TURNS_DDL)
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM forge_turns WHERE turn_id = ?",  # noqa: S608
                    (turn_id,),
                ).fetchone()
            return _row_to_turn(row) if row is not None else None

        return await asyncio.to_thread(_run)
