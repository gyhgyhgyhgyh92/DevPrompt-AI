"""目录浏览 I/O（F-601 页内文件资源管理器数据源，GET /project/browse）。

列出目录 + 文件（含名称/修改时间/大小元数据，资源管理器样式展示）；驱动器列表以
A-Z 探测实现（`os.listdrives()` 需 Python 3.12+，项目基线 3.10，见 pyproject）。
排序由后端固定：目录在前、文件在后，各自名称不区分大小写升序（前端零排序逻辑）。
同步磁盘 I/O 经 asyncio.to_thread 包装（MUST-13：不在事件循环直接阻塞）。

路径安全（MUST-20）：入口统一 normpath/abspath 规范化；不存在 → 2001、
不可读（权限）→ 2002；错误文案不含路径本体（MUST-19）。单条目 OSError（受保护
文件/坏链接等）跳过不中断整表；条目总数超过 MAX_BROWSE_ENTRIES 按既定序截断并置
truncated（响应携带标志供前端提示）。
"""

from __future__ import annotations

import asyncio
import os
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from devprompt_ai.domain.errors import RetrievalError

MAX_BROWSE_ENTRIES = 500
"""单次目录列表条目上限：超大目录（如 C:\\Windows\\System32）截断保护。"""


@dataclass(frozen=True)
class BrowseEntry:
    """目录/文件条目：展示名 + 完整路径 + 类型与元数据。"""

    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int | None = None  # 文件字节数；目录与驱动器为 None（资源管理器不展示目录大小）
    modified_at: str | None = None  # 本地时间 ISO（YYYY-MM-DDTHH:MM:SS）；驱动器为 None


@dataclass(frozen=True)
class BrowseListing:
    """一次浏览结果；``path`` 为空串表示驱动器列表模式。"""

    path: str
    # 上级目录：None=无上级（驱动器列表）；""=驱动器根（回驱动器列表）；其余=上级路径
    parent: str | None
    entries: tuple[BrowseEntry, ...] = ()
    truncated: bool = False


def _list_drives_sync() -> BrowseListing:
    """逐盘符探测（A-Z）：存在即为可用驱动器，路径取 ``X:\\`` 形态（kind=dir 可进入）。"""
    entries = tuple(
        BrowseEntry(name=f"{letter}:\\", path=f"{letter}:\\", kind="dir")
        for letter in string.ascii_uppercase
        if os.path.isdir(f"{letter}:\\")
    )
    return BrowseListing(path="", parent=None, entries=entries)


def _iter_entries(root: str) -> list[BrowseEntry]:
    """列出目录 + 文件（目录在前、文件在后，各自名称升序）。

    Windows 上 ``DirEntry.stat()`` 数据来自目录扫描（无额外系统调用）；单条目
    OSError（受保护文件/坏链接）跳过不中断整表。
    """
    dirs: list[BrowseEntry] = []
    files: list[BrowseEntry] = []
    with os.scandir(root) as it:
        for fs_entry in it:
            try:
                is_dir = fs_entry.is_dir()
                stat = fs_entry.stat()
                item = BrowseEntry(
                    name=fs_entry.name,
                    path=os.path.join(root, fs_entry.name),
                    kind="dir" if is_dir else "file",
                    size=None if is_dir else stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                )
            except OSError:
                continue
            (dirs if is_dir else files).append(item)
    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.name.lower())
    return [*dirs, *files]


def _parent_of(normalized: str) -> str:
    """上级目录：驱动器根 → ""（回驱动器列表）；UNC 根/异常 → ""。"""
    _, tail = os.path.splitdrive(normalized)
    if tail in ("\\", "/"):
        return ""
    parent = os.path.dirname(normalized)
    if parent == normalized:  # UNC 共享根等无法再上级：回驱动器列表
        return ""
    return parent


def _list_entries_sync(path: str) -> BrowseListing:
    normalized = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(normalized):
        raise RetrievalError("目录不存在或不可访问", code=2001)
    try:
        items = _iter_entries(normalized)
    except PermissionError as exc:
        raise RetrievalError("没有权限访问该目录", code=2002) from exc
    truncated = len(items) > MAX_BROWSE_ENTRIES
    return BrowseListing(
        path=normalized,
        parent=_parent_of(normalized),
        entries=tuple(items[:MAX_BROWSE_ENTRIES]),
        truncated=truncated,
    )


async def list_drives() -> BrowseListing:
    """驱动器列表（path 空串模式的浏览结果）。"""
    return await asyncio.to_thread(_list_drives_sync)


async def list_subdirectories(path: str) -> BrowseListing:
    """列出 path 下的一级条目（目录 + 文件，含元数据；规范化 + 存在性/权限校验）。"""
    return await asyncio.to_thread(_list_entries_sync, path)
