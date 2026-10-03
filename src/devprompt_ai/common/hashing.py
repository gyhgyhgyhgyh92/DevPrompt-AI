"""哈希纯工具：原句 sha256、mtime 摘要（MUST-14 缓存键的基元）。

mtime_digest 只做纯计算——路径与 mtime 由调用方收集（显式传入，无隐式 I/O，§4.7）。
"""

from __future__ import annotations

import hashlib


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def mtime_digest(entries: list[tuple[str, int]]) -> str:
    """将 (路径, mtime_ns) 列表排序后拼接待摘要串，输出 sha256 前 16 位。

    排序保证与传入顺序无关；mtime 变化必然改变摘要（MUST-14 失效条件）。
    """
    lines = "\n".join(f"{path}|{mtime}" for path, mtime in sorted(entries))
    return sha256_hex(lines)[:16]
