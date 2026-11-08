"""token 账本（SQLite）：按轮记账，供成本汇总与压缩经济性判断。

只记数字，不记正文与原句（MUST-19）。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from devprompt_ai.memory.schema import TOKEN_LEDGER_DDL

_BUSY_TIMEOUT_MS = 5000


class SQLiteTokenLedger:
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
        session_id: str,
        model_id: str = "",
        run_id: str = "",
        turn_index: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(TOKEN_LEDGER_DDL)
                conn.execute(
                    "INSERT INTO token_ledger"
                    " (session_id, run_id, turn_index, model_id,"
                    " prompt_tokens, completion_tokens, cached_tokens)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        run_id,
                        turn_index,
                        model_id,
                        prompt_tokens,
                        completion_tokens,
                        cached_tokens,
                    ),
                )

        await asyncio.to_thread(_run)

    async def totals(self, session_id: str) -> dict[str, int]:
        """会话累计用量；无记录时返回全 0（不抛异常）。"""

        def _run() -> dict[str, int]:
            with self._connect() as conn:
                conn.executescript(TOKEN_LEDGER_DDL)
                row = conn.execute(
                    "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),"
                    " COALESCE(SUM(cached_tokens),0) FROM token_ledger WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if not row:
                return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
            return {
                "prompt_tokens": int(row[0]),
                "completion_tokens": int(row[1]),
                "cached_tokens": int(row[2]),
            }

        return await asyncio.to_thread(_run)
