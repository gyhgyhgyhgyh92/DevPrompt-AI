"""目录浏览 I/O（F-601「选择文件夹（本地）」页内浏览器数据源，GET /project/browse）。

仅列目录不列文件——本交互目的即选择文件夹；驱动器列表以 A-Z 探测实现
（`os.listdrives()` 需 Python 3.12+，项目基线 3.10，见 pyproject requires-python）。
同步磁盘 I/O 经 asyncio.to_thread 包装（MUST-13：不在事件循环直接阻塞）。

路径安全（MUST-20）：入口统一 normpath/abspath 规范化；不存在 → 2001、
不可读（权限）→ 2002；错误文案不含路径本体（MUST-19）。单目录条目超过
MAX_BROWSE_ENTRIES 按名称序截断并置 truncated（响应携带标志供前端提示）。
"""

from __future__ import annotations

import asyncio
import os
import string
from dataclasses import dataclass

from devprompt_ai.domain.errors import RetrievalError

MAX_BROWSE_ENTRIES = 500
"""单次目录列表条目上限：超大目录（如 C:\\Windows\\System32）截断保护。"""


@dataclass(frozen=True)
class BrowseEntry:
    """目录条目：展示名 + 完整路径。"""

    name: str
    path: str


@dataclass(frozen=True)
class BrowseListing:
    """一次浏览结果；``path`` 为空串表示驱动器列表模式。"""

    path: str
    # 上级目录：None=无上级（驱动器列表）；""=驱动器根（回驱动器列表）；其余=上级路径
    parent: str | None
    entries: tuple[BrowseEntry, ...] = ()
    truncated: bool = False


def _list_drives_sync() -> BrowseListing:
    """逐盘符探测（A-Z）：存在即为可用驱动器，路径取 ``X:\\`` 形态。"""
    entries = tuple(
        BrowseEntry(name=f"{letter}:\\", path=f"{letter}:\\")
        for letter in string.ascii_uppercase
        if os.path.isdir(f"{letter}:\\")
    )
    return BrowseListing(path="", parent=None, entries=entries)


def _iter_subdir_names(root: str) -> list[str]:
    """一级子目录名（跟随符号链接/junction；单条目 OSError 跳过不中断整表）。"""
    names: list[str] = []
    with os.scandir(root) as it:
        for entry in it:
            try:
                if entry.is_dir():
                    names.append(entry.name)
            except OSError:
                continue
    names.sort(key=str.lower)
    return names


def _parent_of(normalized: str) -> str:
    """上级目录：驱动器根 → ""（回驱动器列表）；UNC 根/异常 → ""。"""
    _, tail = os.path.splitdrive(normalized)
    if tail in ("\\", "/"):
        return ""
    parent = os.path.dirname(normalized)
    if parent == normalized:  # UNC 共享根等无法再上级：回驱动器列表
        return ""
    return parent


def _list_subdirs_sync(path: str) -> BrowseListing:
    normalized = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(normalized):
        raise RetrievalError("目录不存在或不可访问", code=2001)
    try:
        names = _iter_subdir_names(normalized)
    except PermissionError as exc:
        raise RetrievalError("没有权限访问该目录", code=2002) from exc
    truncated = len(names) > MAX_BROWSE_ENTRIES
    entries = tuple(
        BrowseEntry(name=name, path=os.path.join(normalized, name))
        for name in names[:MAX_BROWSE_ENTRIES]
    )
    return BrowseListing(
        path=normalized, parent=_parent_of(normalized), entries=entries, truncated=truncated
    )


async def list_drives() -> BrowseListing:
    """驱动器列表（path 空串模式的浏览结果）。"""
    return await asyncio.to_thread(_list_drives_sync)


async def list_subdirectories(path: str) -> BrowseListing:
    """列出 path 下的一级子目录（规范化 + 存在性/权限校验）。"""
    return await asyncio.to_thread(_list_subdirs_sync, path)
