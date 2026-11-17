"""仓库符号图存储（SQLite）：符号、边与反向依赖。

写入按文件整体替换（同一文件的旧符号/边先删后插），避免增量合并出脏数据。
反向查询用 BFS，默认 3 跳——超过 3 跳的「影响」噪声大于信号。
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from devprompt_ai.domain.retrieval.physarum import reinforce
from devprompt_ai.memory.schema import REPO_GRAPH_DDL

_BUSY_TIMEOUT_MS = 5000

#: 符号定义：(name, kind, line, end_line, signature)
SymbolRow = tuple[str, str, int, int, str]
#: 边：(dst_path, kind, symbol)
EdgeRow = tuple[str, str, str]


def _ensure_edge_columns(conn: sqlite3.Connection) -> None:
    """旧库升级：weight/updated_at 列后加（CREATE TABLE IF NOT EXISTS 不会补列）。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(repo_edges)").fetchall()}
    if "weight" not in columns:
        conn.execute("ALTER TABLE repo_edges ADD COLUMN weight REAL NOT NULL DEFAULT 1.0")
    if "updated_at" not in columns:
        conn.execute(
            "ALTER TABLE repo_edges ADD COLUMN updated_at TEXT NOT NULL"
            " DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
        )


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _hours_since(timestamp: str, now: datetime) -> float:
    """距上次访问的小时数；时间戳损坏按 0（不衰减）处理。"""
    try:
        last = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (now - last).total_seconds() / 3600.0)


class SQLiteRepoIndex:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return conn

    async def replace_file(
        self,
        project_root: str,
        path: str,
        symbols: Sequence[SymbolRow],
        edges: Sequence[EdgeRow],
    ) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                _ensure_edge_columns(conn)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        "DELETE FROM repo_symbols WHERE project_root = ? AND path = ?",
                        (project_root, path),
                    )
                    conn.execute(
                        "DELETE FROM repo_edges WHERE project_root = ? AND src_path = ?",
                        (project_root, path),
                    )
                    conn.executemany(
                        "INSERT OR REPLACE INTO repo_symbols"
                        " (project_root, path, symbol, kind, line, end_line, signature)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            (project_root, path, name, kind, line, end_line, signature)
                            for name, kind, line, end_line, signature in symbols
                        ],
                    )
                    conn.executemany(
                        "INSERT OR REPLACE INTO repo_edges"
                        " (project_root, src_path, dst_path, kind, symbol)"
                        " VALUES (?, ?, ?, ?, ?)",
                        [(project_root, path, dst, kind, symbol) for dst, kind, symbol in edges],
                    )
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise

        await asyncio.to_thread(_run)

    async def reverse_dependents(
        self, project_root: str, path: str, *, max_hops: int = 3
    ) -> dict[str, int]:
        """返回 {依赖方路径: 跳数}，不含起点自身。"""

        def _run() -> dict[str, int]:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                seen: dict[str, int] = {}
                frontier = [path]
                for hop in range(1, max(1, max_hops) + 1):
                    if not frontier:
                        break
                    placeholders = ",".join("?" for _ in frontier)
                    rows = conn.execute(
                        f"SELECT DISTINCT src_path FROM repo_edges"  # noqa: S608 - 占位符数量由入参决定
                        f" WHERE project_root = ? AND dst_path IN ({placeholders})"
                        " AND kind IN ('import', 'call')",
                        (project_root, *frontier),
                    ).fetchall()
                    frontier = [
                        str(row[0])
                        for row in rows
                        if str(row[0]) not in seen and str(row[0]) != path
                    ]
                    for item in frontier:
                        seen[item] = hop
            return seen

        return await asyncio.to_thread(_run)

    async def reinforce_edges(self, project_root: str, pairs: Sequence[tuple[str, str]]) -> None:
        """I6 访问强化：对 (src→dst) 边做「按流逝时间衰减 + 单次强化」后写回。

        dt 按小时计（tau=300 ≈ 半衰期 8.7 天），权重上限由 physarum 纯函数约束。
        """

        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                _ensure_edge_columns(conn)
                now = datetime.now(timezone.utc)
                for src, dst in dict.fromkeys(pairs):
                    row = conn.execute(
                        "SELECT weight, updated_at FROM repo_edges"
                        " WHERE project_root = ? AND src_path = ? AND dst_path = ?"
                        " ORDER BY updated_at DESC LIMIT 1",
                        (project_root, src, dst),
                    ).fetchone()
                    base = float(row[0]) if row is not None else 1.0
                    dt = _hours_since(str(row[1]), now) if row is not None and row[1] else 0.0
                    conn.execute(
                        "UPDATE repo_edges SET weight = ?, updated_at = ?"
                        " WHERE project_root = ? AND src_path = ? AND dst_path = ?",
                        (reinforce(base, flow=1.0, dt=dt), _now_iso(), project_root, src, dst),
                    )

        await asyncio.to_thread(_run)

    async def edge_weights(self, project_root: str, dst_path: str) -> dict[str, float]:
        """dst 的各依赖边权重（{src: weight}），影响面同跳数内的次级排序用。"""

        def _run() -> dict[str, float]:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                _ensure_edge_columns(conn)
                rows = conn.execute(
                    "SELECT src_path, MAX(weight) FROM repo_edges"
                    " WHERE project_root = ? AND dst_path = ? GROUP BY src_path",
                    (project_root, dst_path),
                ).fetchall()
            return {str(src): float(weight) for src, weight in rows}

        return await asyncio.to_thread(_run)

    async def symbols_named(self, project_root: str, name: str) -> list[tuple[str, str, int]]:
        """按符号名查定义位置（(path, kind, line)）——取证与影响面展示用。"""

        def _run() -> list[tuple[str, str, int]]:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                rows = conn.execute(
                    "SELECT path, kind, line FROM repo_symbols"
                    " WHERE project_root = ? AND symbol = ? ORDER BY path, line",
                    (project_root, name),
                ).fetchall()
            return [(str(a), str(b), int(c)) for a, b, c in rows]

        return await asyncio.to_thread(_run)

    async def clear(self, project_root: str) -> None:
        def _run() -> None:
            with self._connect() as conn:
                conn.executescript(REPO_GRAPH_DDL)
                conn.execute("DELETE FROM repo_symbols WHERE project_root = ?", (project_root,))
                conn.execute("DELETE FROM repo_edges WHERE project_root = ?", (project_root,))

        await asyncio.to_thread(_run)
