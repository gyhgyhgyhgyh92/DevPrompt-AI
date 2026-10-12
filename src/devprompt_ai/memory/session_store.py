"""F-501 L1 会话存储（SQLite，WAL）：CAS 乐观锁写入（MUST-11）。SQL 限于 memory/（MUST-06）。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from devprompt_ai.domain.models import FlowSession, SessionSummary
from devprompt_ai.memory.schema import SESSIONS_DDL

_BUSY_TIMEOUT_MS = 5000


class SQLiteSessionStore:
    """每操作独立连接 + asyncio.to_thread（sqlite3 同步 API 的异步包装，MUST-13）。"""

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
                conn.executescript(SESSIONS_DDL)

        await asyncio.to_thread(_run)

    async def create(self, session: FlowSession) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO forge_sessions (session_id, user_id, state, version, payload)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        session.session_id,
                        session.user_id,
                        session.state,
                        session.version,
                        json.dumps(session.data, ensure_ascii=False),
                    ),
                )

        await asyncio.to_thread(_run)

    async def load(self, session_id: str) -> FlowSession | None:
        def _run() -> FlowSession | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT user_id, state, version, payload FROM forge_sessions"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if row is None:
                return None
            return FlowSession(
                session_id=session_id,
                user_id=row[0],
                state=row[1],
                version=row[2],
                data=json.loads(row[3]),
            )

        return await asyncio.to_thread(_run)

    async def save(self, session: FlowSession) -> bool:
        def _run() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE forge_sessions SET state = ?, version = version + 1, payload = ?"
                    " WHERE session_id = ? AND version = ?",
                    (
                        session.state,
                        json.dumps(session.data, ensure_ascii=False),
                        session.session_id,
                        session.version,
                    ),
                )
                if cur.rowcount == 0:
                    return False
            session.version += 1
            return True

        return await asyncio.to_thread(_run)

    async def list_recent(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        """GET /history 数据源：pinned 优先 + updated_at 倒序；脱敏——payload 仅取项目名与标题。"""

        def _run() -> list[SessionSummary]:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT session_id, state, payload, updated_at FROM forge_sessions"
                    " WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
            out: list[SessionSummary] = []
            for session_id, state, payload_raw, updated_at in rows:
                try:
                    payload = json.loads(payload_raw)
                except json.JSONDecodeError:
                    payload = {}
                project = Path(str(payload.get("project_root", ""))).name
                custom = payload.get("custom_title")
                title = str(custom) if custom else str(payload.get("sentence", "")).strip()[:40]
                out.append(
                    SessionSummary(
                        session_id=session_id,
                        state=state,
                        project=project,
                        updated_at=updated_at,
                        title=title,
                        pinned=bool(payload.get("pinned", False)),
                    )
                )
            # 全部取出后 Python 排序再截取：置顶优先 + updated_at 倒序。
            # 会话量小（本地工具），避免 SQL 排序先行截断导致置顶项被 limit 丢出。
            out.sort(key=lambda s: (s.pinned, s.updated_at), reverse=True)
            return out[:limit]

        return await asyncio.to_thread(_run)

    async def delete(self, session_id: str) -> bool:
        """物理删除会话：DELETE FROM forge_sessions；rowcount>0 为 True（不存在返回 False）。"""

        def _run() -> bool:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM forge_sessions WHERE session_id = ?", (session_id,))
                return cur.rowcount > 0

        return await asyncio.to_thread(_run)
