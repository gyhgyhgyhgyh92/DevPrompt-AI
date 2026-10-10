"""F-503 L3 偏好存储（SQLite）：向量 UPSERT + 采纳历史追加。SQL 限于 memory/（MUST-06）。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from devprompt_ai.domain.ranking.ports import AdoptionRecord, VariantFeatures
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.memory.schema import PREFERENCE_DDL

_BUSY_TIMEOUT_MS = 5000
# F-503「保留最近约 30 轮有效信号」：history 默认取最近 30 条采纳记录。
_HISTORY_DEFAULT_LIMIT = 30


def _features_from_json(raw: str) -> VariantFeatures:
    """features_json → 四维特征（显式重建，类型收窄 + 写入侧契约校验）。"""
    data = json.loads(raw)
    return {
        "detail_level": float(data["detail_level"]),
        "include_diff": float(data["include_diff"]),
        "specify_tests": float(data["specify_tests"]),
        "max_files_norm": float(data["max_files_norm"]),
    }


class SQLitePreferenceStore:
    """每操作独立连接 + asyncio.to_thread（sqlite3 同步 API 的异步包装，同会话存储模式 MUST-13）。

    user_id 为 preference_vectors 主键 / adoption_history 查询分区键（用户间数据隔离）。
    """

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
                conn.executescript(PREFERENCE_DDL)

        await asyncio.to_thread(_run)

    async def load(self, user_id: str) -> dict[str, float]:
        """读偏好向量；无记录返回初始中性向量（F-402：无历史数据不影响排序）。"""

        def _run() -> dict[str, float]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT detail_level, include_diff, specify_tests, max_files_norm"
                    " FROM preference_vectors WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            if row is None:
                return dict(INITIAL_PREFERENCE)
            return {
                "detail_level": float(row[0]),
                "include_diff": float(row[1]),
                "specify_tests": float(row[2]),
                "max_files_norm": float(row[3]),
            }

        return await asyncio.to_thread(_run)

    async def save(self, user_id: str, vector: dict[str, float]) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO preference_vectors"
                    " (user_id, detail_level, include_diff, specify_tests, max_files_norm)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(user_id) DO UPDATE SET"
                    " detail_level = excluded.detail_level,"
                    " include_diff = excluded.include_diff,"
                    " specify_tests = excluded.specify_tests,"
                    " max_files_norm = excluded.max_files_norm,"
                    " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                    (
                        user_id,
                        vector["detail_level"],
                        vector["include_diff"],
                        vector["specify_tests"],
                        vector["max_files_norm"],
                    ),
                )

        await asyncio.to_thread(_run)

    async def record_adoption(self, rec: AdoptionRecord) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO adoption_history"
                    " (user_id, session_id, variant, edited, edited_text_ratio, features_json)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        rec.user_id,
                        rec.session_id,
                        rec.variant,
                        int(rec.edited),
                        rec.edited_text_ratio,
                        json.dumps(rec.features, ensure_ascii=False, sort_keys=True),
                    ),
                )

        await asyncio.to_thread(_run)

    async def history(
        self, user_id: str, limit: int = _HISTORY_DEFAULT_LIMIT
    ) -> list[AdoptionRecord]:
        """采纳历史（最新在前，最多 limit 条；仅限本 user_id 分区）。"""

        def _run() -> list[AdoptionRecord]:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT variant, edited, edited_text_ratio, features_json, session_id"
                    " FROM adoption_history WHERE user_id = ?"
                    " ORDER BY id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            return [
                AdoptionRecord(
                    user_id=user_id,
                    session_id=row[4],
                    variant=row[0],  # 写入侧仅落 A/B/C（AdoptionRecord.variant 契约）
                    edited=bool(row[1]),
                    edited_text_ratio=float(row[2]),
                    features=_features_from_json(row[3]),
                )
                for row in rows
            ]

        return await asyncio.to_thread(_run)
