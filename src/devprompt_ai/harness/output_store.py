"""原始输出落盘（C3）：截断前先存全量，给模型一个可回读的指针。

为什么落临时目录而不是数据库：这些是短命的中间产物，进库会让事件表膨胀；
一小时未访问即清理。文件内容可能含用户代码，不写日志（MUST-19）。
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import time
from pathlib import Path

_RAW_DIR = Path(tempfile.gettempdir()) / "devprompt-raw"
_MAX_AGE_S = 3600.0


def raw_path(call_id: str) -> Path:
    digest = hashlib.sha256(call_id.encode("utf-8")).hexdigest()[:24]
    return _RAW_DIR / f"{digest}.raw"


async def persist(call_id: str, text: str) -> str:
    """写入并返回可回读路径；写失败返回空串（调用方继续走截断展示）。"""
    path = raw_path(call_id)

    def _run() -> str:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            return ""
        return str(path)

    return await asyncio.to_thread(_run)


async def read(path: str) -> str | None:
    def _run() -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return None

    return await asyncio.to_thread(_run)


async def read_by_id(artifact_id: str) -> str | None:
    """按 ``raw_path().stem`` 的文件名摘要取回内容（persist 的逆向入口）。"""
    return await read(str(_RAW_DIR / f"{artifact_id}.raw"))


def cleanup(older_than_s: float = _MAX_AGE_S) -> int:
    """删除过期文件，返回删除数量；目录不存在视为 0。"""
    if not _RAW_DIR.exists():
        return 0
    cutoff = time.time() - max(0.0, older_than_s)
    removed = 0
    for item in _RAW_DIR.glob("*.raw"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed
