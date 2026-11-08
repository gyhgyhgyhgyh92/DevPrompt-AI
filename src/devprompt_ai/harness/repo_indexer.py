"""仓库索引器（I4）：扫描 Python 文件、建符号与导入边，落 SQLite。

上限 800 文件 / 深度 8：超过这个量级，索引耗时与噪声都开始超过收益；
解析失败的文件跳过并计数，不阻断整次索引。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Final

from devprompt_ai.harness.pygraph import import_edges, parse_python
from devprompt_ai.memory.repo_index import SQLiteRepoIndex

MAX_FILES: Final[int] = 800
MAX_DEPTH: Final[int] = 8
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "dist", "build", ".mypy_cache"}
)


def collect_python_files(root: str, *, max_files: int = MAX_FILES) -> list[str]:
    base = Path(root)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        for name in filenames:
            if not name.endswith(".py"):
                continue
            found.append(str(Path(dirpath, name).relative_to(base)).replace("\\", "/"))
            if len(found) >= max_files:
                return found
    return found


async def index_project(
    db_path: str,
    root: str,
    *,
    max_files: int = MAX_FILES,
) -> tuple[int, int]:
    """返回 (索引文件数, 解析失败数)；同一文件重复调用会整体替换旧数据。"""
    files = collect_python_files(root, max_files=max_files)
    known = set(files)
    index = SQLiteRepoIndex(db_path)
    indexed = 0
    failed = 0

    def _read(rel: str) -> str:
        return Path(root, rel).read_text(encoding="utf-8", errors="replace")

    for rel in files:
        try:
            source = await asyncio.to_thread(_read, rel)
        except OSError:
            failed += 1
            continue
        parsed = parse_python(rel, source)
        if parsed.errors:
            failed += 1
            continue
        symbols = [(s.name, s.kind, s.line, s.end_line, s.signature) for s in parsed.symbols]
        edges = [(dst, "import", "") for _, dst in import_edges(parsed, known)]
        await index.replace_file(root, rel, symbols, edges)
        indexed += 1
    return indexed, failed


async def impact_for(db_path: str, root: str, path: str, *, max_hops: int = 3) -> dict[str, int]:
    """查询某文件的反向依赖（谁会被它波及）。"""
    return await SQLiteRepoIndex(db_path).reverse_dependents(root, path, max_hops=max_hops)
