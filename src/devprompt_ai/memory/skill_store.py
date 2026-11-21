"""自定义 Skill 存储（SQLite，2026-11-21）：只有用户界面新建的技能落库。

目录型技能不进表——它们以文件为真源，扫描结果只读，避免两处真源漂移。
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devprompt_ai.domain.skills.models import Skill, SkillMeta

_BUSY_TIMEOUT_MS = 5000

SKILLS_DDL = """
CREATE TABLE IF NOT EXISTS skills (
  skill_id    TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  body        TEXT NOT NULL DEFAULT '',
  domains     TEXT NOT NULL DEFAULT '',
  enabled     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name ON skills (name);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")


class SQLiteSkillStore:
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
                conn.executescript(SKILLS_DDL)

        await asyncio.to_thread(_run)

    async def list_all(self) -> list[Skill]:
        def _run() -> list[Skill]:
            with self._connect() as conn:
                conn.executescript(SKILLS_DDL)
                rows = conn.execute(
                    "SELECT skill_id, name, description, body, domains, enabled"
                    " FROM skills ORDER BY name"
                ).fetchall()
            return [
                Skill(
                    meta=SkillMeta(
                        name=str(row[1]),
                        description=str(row[2]),
                        source="custom",
                        domains=tuple(
                            item for item in str(row[4]).split(",") if item.strip()
                        ),
                        skill_id=str(row[0]),
                        enabled=bool(row[5]),
                    ),
                    body=str(row[3]),
                )
                for row in rows
            ]

        return await asyncio.to_thread(_run)

    async def upsert(
        self,
        *,
        name: str,
        description: str = "",
        body: str = "",
        domains: list[str] | None = None,
        enabled: bool = True,
        skill_id: str = "",
    ) -> Skill:
        sid = skill_id.strip() or uuid.uuid4().hex
        domains_text = ",".join(item.strip() for item in (domains or []) if item.strip())

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(SKILLS_DDL)
                now = _now()
                conn.execute(
                    "INSERT INTO skills (skill_id, name, description, body, domains,"
                    " enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(skill_id) DO UPDATE SET name=? , description=?, body=?,"
                    " domains=?, enabled=?, updated_at=?",
                    (
                        sid,
                        name.strip(),
                        description,
                        body,
                        domains_text,
                        int(enabled),
                        now,
                        now,
                        name.strip(),
                        description,
                        body,
                        domains_text,
                        int(enabled),
                        now,
                    ),
                )

        await asyncio.to_thread(_run)
        return Skill(
            meta=SkillMeta(
                name=name.strip(),
                description=description,
                source="custom",
                domains=tuple(item for item in domains_text.split(",") if item),
                skill_id=sid,
                enabled=enabled,
            ),
            body=body,
        )

    async def delete(self, skill_id: str) -> bool:
        def _run() -> bool:
            with self._connect() as conn:
                conn.executescript(SKILLS_DDL)
                cursor = conn.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
                return bool(cursor.rowcount)

        return await asyncio.to_thread(_run)

    async def get(self, skill_id: str) -> dict[str, Any] | None:
        def _run() -> dict[str, Any] | None:
            with self._connect() as conn:
                conn.executescript(SKILLS_DDL)
                row = conn.execute(
                    "SELECT skill_id, name, description, body, domains, enabled"
                    " FROM skills WHERE skill_id = ?",
                    (skill_id,),
                ).fetchone()
            if row is None:
                return None
            return {
                "skill_id": str(row[0]),
                "name": str(row[1]),
                "description": str(row[2]),
                "body": str(row[3]),
                "domains": [item for item in str(row[4]).split(",") if item],
                "enabled": bool(row[5]),
            }

        return await asyncio.to_thread(_run)
