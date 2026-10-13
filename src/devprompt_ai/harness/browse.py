"""目录浏览 I/O（F-601 页内文件资源管理器数据源，GET /project/browse）。

仅列目录（本交互目的即选择文件夹，文件不出现——用户裁定），条目携带修改时间；
驱动器列表以 A-Z 探测实现（`os.listdrives()` 需 Python 3.12+，项目基线 3.10，见
pyproject）。排序由后端固定：名称不区分大小写升序（前端零排序逻辑）。
同步磁盘 I/O 经 asyncio.to_thread 包装（MUST-13：不在事件循环直接阻塞）。

路径安全（MUST-20）：入口统一 normpath/abspath 规范化；不存在 → 2001、
不可读（权限）→ 2002；错误文案不含路径本体（MUST-19）。单条目 OSError（受保护
目录/坏链接等）跳过不中断整表；条目总数超过 MAX_BROWSE_ENTRIES 按既定序截断并置
truncated（响应携带标志供前端提示）。
"""

from __future__ import annotations

import asyncio
import os
import string
from dataclasses import dataclass
from datetime import datetime

from devprompt_ai.domain.errors import RetrievalError

MAX_BROWSE_ENTRIES = 500
"""单次目录列表条目上限：超大目录（如 C:\\Windows\\System32）截断保护。"""

MAX_SEARCH_DEPTH = 6
"""递归搜索层数上限（相对基准目录；防深层目录树跑飞）。"""

MAX_SEARCH_NODES = 20000
"""递归搜索访问目录数上限（防超宽目录树跑飞；达上限即截断）。"""


@dataclass(frozen=True)
class BrowseEntry:
    """目录条目：展示名 + 完整路径 + 修改时间（搜索结果附相对基准目录的父路径）。"""

    name: str
    path: str
    modified_at: str | None = None  # 本地时间 ISO（YYYY-MM-DDTHH:MM:SS）；驱动器为 None
    rel_parent: str | None = None  # 搜索结果专用：直接子级为 ""，更深为 a\b；普通列举为 None


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


def _iter_entries(root: str) -> list[BrowseEntry]:
    """列出子目录（名称升序；仅目录——文件不出现，用户裁定）。

    Windows 上 ``DirEntry.stat()`` 数据来自目录扫描（无额外系统调用）；单条目
    OSError（受保护目录/坏链接）跳过不中断整表。
    """
    entries: list[BrowseEntry] = []
    with os.scandir(root) as it:
        for fs_entry in it:
            try:
                if not fs_entry.is_dir():
                    continue
                stat = fs_entry.stat()
                item = BrowseEntry(
                    name=fs_entry.name,
                    path=os.path.join(root, fs_entry.name),
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                )
            except OSError:
                continue
            entries.append(item)
    entries.sort(key=lambda e: e.name.lower())
    return entries


def _parent_of(normalized: str) -> str:
    """上级目录：驱动器根 → ""（回驱动器列表）；UNC 根/异常 → ""。"""
    _, tail = os.path.splitdrive(normalized)
    if tail in ("\\", "/"):
        return ""
    parent = os.path.dirname(normalized)
    if parent == normalized:  # UNC 共享根等无法再上级：回驱动器列表
        return ""
    return parent


def _iter_search_matches(root: str, query: str) -> tuple[list[BrowseEntry], bool]:
    """递归搜索 root 子树中名称包含 query 的目录（忽略大小写）。

    返回 (命中条目, 是否截断)。命中条目按（深度, 相对父路径, 名称）升序；三重上限——
    深度 MAX_SEARCH_DEPTH、访问目录数 MAX_SEARCH_NODES、命中数 MAX_BROWSE_ENTRIES——
    任一触顶即停止并置截断。文件不参与（本交互只选文件夹）；单条目 OSError 跳过。
    """
    target = query.strip().casefold()
    matches: list[BrowseEntry] = []
    truncated = False
    visited = 0
    # (目录绝对路径, 相对基准的父路径, 深度)
    stack: list[tuple[str, str, int]] = [(root, "", 1)]
    while stack:
        current, rel_parent, depth = stack.pop()
        visited += 1
        if visited > MAX_SEARCH_NODES or depth > MAX_SEARCH_DEPTH:
            truncated = True
            break
        try:
            with os.scandir(current) as it:
                children: list[tuple[str, str]] = []
                for fs_entry in it:
                    try:
                        if not fs_entry.is_dir():
                            continue
                        child_path = os.path.join(current, fs_entry.name)
                        stat = fs_entry.stat()
                    except OSError:
                        continue
                    if target in fs_entry.name.casefold():
                        matches.append(
                            BrowseEntry(
                                name=fs_entry.name,
                                path=child_path,
                                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(
                                    timespec="seconds"
                                ),
                                rel_parent=rel_parent,
                            )
                        )
                        if len(matches) >= MAX_BROWSE_ENTRIES:
                            truncated = True
                            break
                    child_rel = (
                        fs_entry.name if rel_parent == "" else f"{rel_parent}\\{fs_entry.name}"
                    )
                    children.append((child_path, child_rel))
        except (PermissionError, OSError):
            continue  # 不可读目录跳过，不中断整次搜索
        if len(matches) >= MAX_BROWSE_ENTRIES:
            break
        for child_path, child_rel in children:
            stack.append((child_path, child_rel, depth + 1))
    matches.sort(
        key=lambda e: (
            0 if not e.rel_parent else e.rel_parent.count("\\") + 1,  # 相对深度（浅层优先）
            (e.rel_parent or "").casefold(),
            e.name.casefold(),
        )
    )
    return matches, truncated


def _list_entries_sync(path: str, query: str = "") -> BrowseListing:
    normalized = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(normalized):
        raise RetrievalError("目录不存在或不可访问", code=2001)
    if query.strip() != "":
        matches, truncated = _iter_search_matches(normalized, query)
        return BrowseListing(
            path=normalized,  # 基准目录：搜索范围不随结果漂移（前端据此保持 scope）
            parent=_parent_of(normalized),
            entries=tuple(matches),
            truncated=truncated,
        )
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


async def list_subdirectories(path: str, query: str = "") -> BrowseListing:
    """列出 path 下条目：query 非空 = 子树递归搜索（仅目录）；否则一级子目录列举。"""
    return await asyncio.to_thread(_list_entries_sync, path, query)
