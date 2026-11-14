"""L2 项目记忆的结构化存储（2026-10-20）：SQLite 为唯一读写真源。

为什么不再走 git notes：那是一条追加写、无 key 的自由文本 blob——**不是没读，是无法读**
（没有检索入口），任何注入都只能退化为把 8KB 全文塞进 prompt。这里改为
`(project_root, kind, key)` 主键 + 检索式注入：

    score = confidence × 0.5 ** (age_days / 90) × key_match

- `key_match`：1.0（key 完全匹配）/ 0.6（符号名相同或同文件末段）/ 0
- 取前 N（默认 5），命中回写 `hit_count` + `last_hit_at`（判断记忆是否有用的唯一客观信号）
- `superseded_by` 标记被覆盖的旧记忆，不物理删除

git notes 路线已整体放弃：无法检索、注入退化为全文塞 prompt（见上），不再保留导出函数。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from devprompt_ai.domain.models import ProjectNote
from devprompt_ai.memory.schema import PROJECT_NOTES_DDL

_BUSY_TIMEOUT_MS = 5000
_HALF_LIFE_DAYS = 90.0
_VALUE_LIMIT = 200

_COLUMNS = (
    "project_root, kind, key, value, evidence, confidence, hit_count, last_hit_at, "
    "superseded_by, source"
)


def normalize_key(symbol: str, path: str) -> str:
    """key 归一化（决定命中率）：符号名小写 + `@` + 路径末两段。"""
    segments = [part for part in path.replace("\\", "/").split("/") if part]
    tail = "/".join(segments[-2:]).lower() if segments else ""
    return f"{symbol.strip().lower()}@{tail}"


def score_note(note: ProjectNote, *, target_key: str, age_days: float) -> float:
    """检索打分（纯函数，便于单测）。"""
    if note.key == target_key:
        key_match = 1.0
    elif target_key and (
        note.key.split("@", 1)[0] == target_key.split("@", 1)[0]
        or note.key.split("@", 1)[-1] == target_key.split("@", 1)[-1]
    ):
        key_match = 0.6
    else:
        key_match = 0.0
    decay = 0.5 ** (max(0.0, age_days) / _HALF_LIFE_DAYS)
    return cast(float, note.confidence * decay * key_match)


class SQLiteProjectNoteStore:
    """ProjectNoteStore 的 SQLite 实现（阻塞 I/O 走 to_thread，MUST-13）。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def upsert(self, note: ProjectNote) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(PROJECT_NOTES_DDL)
                conn.execute(
                    f"INSERT INTO project_notes ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?) "  # noqa: S608
                    "ON CONFLICT(project_root, kind, key) DO UPDATE SET "
                    "value=excluded.value, evidence=excluded.evidence, "
                    "confidence=excluded.confidence, superseded_by=excluded.superseded_by, "
                    "source=excluded.source",
                    (
                        note.project_root,
                        note.kind,
                        note.key,
                        note.value[:_VALUE_LIMIT],
                        note.evidence[:_VALUE_LIMIT],
                        note.confidence,
                        note.hit_count,
                        note.last_hit_at or None,
                        note.superseded_by or None,
                        note.source,
                    ),
                )

        await asyncio.to_thread(_run)

    async def record_from_session(self, project_root: str, data: dict[str, Any]) -> None:
        """本轮结束后自动写入 target / decision / rejected_option（自动级记忆）。"""
        target = data.get("target")
        if not isinstance(target, dict) or not target.get("name"):
            return
        key = normalize_key(str(target["name"]), str(target.get("path", "")))
        await self.upsert(
            ProjectNote(
                project_root=project_root,
                kind="target",
                key=key,
                value=f"{target['name']} 位于 {target.get('path', '')}:{target.get('line', 0)}",
                confidence=0.9,
                source="auto",
            )
        )

        # 仅用于 2026-11-11 之前的历史轮次回放：新轮次为单套输出，不再写入 ranking。
        ranking = data.get("ranking")
        decision = ""
        if isinstance(ranking, dict) and ranking.get("variant"):
            decision = str(ranking["variant"])
        variants = [item for item in data.get("variants", []) if isinstance(item, dict)]
        chosen = next((item for item in variants if str(item.get("level")) == decision), None)
        if chosen is None and variants:
            chosen = variants[0]
        if chosen is not None and chosen.get("title"):
            await self.upsert(
                ProjectNote(
                    project_root=project_root,
                    kind="decision",
                    key=key,
                    value=f"选定 {chosen.get('level')}：{chosen.get('title')}",
                    confidence=0.7,
                    source="auto",
                )
            )
        for item in variants:
            if chosen is not None and item.get("level") == chosen.get("level"):
                continue
            if not item.get("title"):
                continue
            await self.upsert(
                ProjectNote(
                    project_root=project_root,
                    kind="rejected_option",
                    key=f"{key}#{item.get('level')}",
                    value=f"未选 {item.get('level')}：{item.get('title')}",
                    confidence=0.5,
                    source="auto",
                )
            )

    async def search(
        self, project_root: str, *, target_key: str = "", limit: int = 5
    ) -> list[ProjectNote]:
        """按 score 降序取前 N，并回写命中计数（批量 UPDATE）。"""

        def _run() -> list[ProjectNote]:
            with self._connect() as conn:
                conn.executescript(PROJECT_NOTES_DDL)
                rows = conn.execute(
                    f"SELECT {_COLUMNS}, "  # noqa: S608 - 常量列名
                    "(julianday('now') - julianday(created_at)) AS age_days "
                    "FROM project_notes WHERE project_root = ? AND superseded_by IS NULL",
                    (project_root,),
                ).fetchall()
                notes: list[ProjectNote] = []
                scored: list[tuple[float, ProjectNote]] = []
                for row in rows:
                    note = ProjectNote(
                        project_root=str(row[0]),
                        kind=str(row[1]),
                        key=str(row[2]),
                        value=str(row[3]),
                        evidence=str(row[4]),
                        confidence=float(row[5]),
                        hit_count=int(row[6]),
                        last_hit_at=str(row[7] or ""),
                        superseded_by=str(row[8] or ""),
                        source=str(row[9]),
                    )
                    notes.append(note)
                    scored.append(
                        (
                            score_note(note, target_key=target_key, age_days=float(row[10] or 0)),
                            note,
                        )
                    )
                scored.sort(key=lambda pair: pair[0], reverse=True)
                hits = [note for score, note in scored[:limit] if score > 0]
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")
                for note in hits:
                    conn.execute(
                        "UPDATE project_notes SET hit_count = hit_count + 1, last_hit_at = ? "
                        "WHERE project_root = ? AND kind = ? AND key = ?",
                        (now, note.project_root, note.kind, note.key),
                    )
                return hits

        return await asyncio.to_thread(_run)
