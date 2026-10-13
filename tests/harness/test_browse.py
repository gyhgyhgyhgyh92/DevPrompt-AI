"""harness/browse.py 单测：仅目录+修改时间、排序、上级推导、截断、错误码。

F-601 页内文件夹选择数据源（GET /project/browse）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from devprompt_ai.domain.errors import RetrievalError
from devprompt_ai.harness.browse import (
    _list_drives_sync,
    _parent_of,
    list_subdirectories,
)

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def test_parent_of_drive_root_returns_empty() -> None:
    """驱动器根：空串（回驱动器列表语义，前端据此决定「返回」目标）。"""
    assert _parent_of("D:\\") == ""
    assert _parent_of("C:\\") == ""


def test_parent_of_subdir_returns_parent() -> None:
    assert _parent_of("D:\\Works\\repo") == "D:\\Works"
    assert _parent_of("D:\\Works") == "D:\\"


async def test_list_entries_only_dirs_with_modified_at(tmp_path: Path) -> None:
    """仅列目录（文件不出现）；名称不区分大小写升序；条目携带 ISO 修改时间。"""
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "zeta").mkdir()
    (tmp_path / "note.txt").write_bytes(b"hello")

    listing = await list_subdirectories(str(tmp_path))

    assert listing.path == str(tmp_path)
    assert listing.truncated is False
    assert [e.name for e in listing.entries] == ["Alpha", "beta", "zeta"]
    for e in listing.entries:
        assert e.path.startswith(str(tmp_path))
        assert e.modified_at is not None and _ISO_RE.match(e.modified_at) is not None


async def test_list_subdirectories_missing_raises_2001(tmp_path: Path) -> None:
    """不存在路径：2001；错误消息不回传路径本体（MUST-19）。"""
    missing = str(tmp_path / "absent-dir")
    with pytest.raises(RetrievalError) as err:
        await list_subdirectories(missing)
    assert err.value.code == 2001
    assert missing not in str(err.value)


async def test_list_subdirectories_truncates_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超过上限：按名称序截断并置 truncated 标志（前端提示）。"""
    import devprompt_ai.harness.browse as browse_module

    monkeypatch.setattr(browse_module, "MAX_BROWSE_ENTRIES", 2)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    listing = await list_subdirectories(str(tmp_path))
    assert [e.name for e in listing.entries] == ["a", "b"]
    assert listing.truncated is True


def test_list_drives_shape() -> None:
    """驱动器列表：path 空串 + parent None；条目无元数据（探测依赖真实盘符，仅验形状）。"""
    listing = _list_drives_sync()
    assert listing.path == ""
    assert listing.parent is None
    assert all(re.fullmatch(r"[A-Z]:\\", e.path) for e in listing.entries)
    assert all(e.modified_at is None for e in listing.entries)


# ---------- 递归搜索（F-601，2026-10-13） ----------


def _build_tree(root: Path) -> None:
    """构造测试树：root/{deep-root, Works/deepseek-a, Works/DevPrompt, Toolkit/deep, alpha}。"""
    (root / "deep-root").mkdir()
    (root / "Works" / "deepseek-a").mkdir(parents=True)
    (root / "Works" / "DevPrompt").mkdir()
    (root / "Toolkit" / "deep").mkdir(parents=True)
    (root / "alpha").mkdir()
    (root / "note.txt").write_bytes(b"x")  # 文件不参与搜索


async def test_search_recursive_matches_with_rel_parent(tmp_path: Path) -> None:
    """递归命中多级子目录；rel_parent 直接子级为 ""、更深为父级相对路径；仅目录、忽略文件名。"""
    _build_tree(tmp_path)
    listing = await list_subdirectories(str(tmp_path), "deep")
    assert listing.path == str(tmp_path)  # 基准目录不变（范围不漂移）
    names = {e.name: e.rel_parent for e in listing.entries}
    assert set(names) == {"deep-root", "deepseek-a", "deep"}  # DevPrompt 不含 "deep"，不应命中
    assert names["deep-root"] == ""  # 基准目录直接子级
    assert names["deepseek-a"] == "Works"
    assert names["deep"] == "Toolkit"
    assert all(e.modified_at is not None for e in listing.entries)


async def test_search_is_case_insensitive_and_sorted_by_depth(tmp_path: Path) -> None:
    """大小写不敏感；结果按（相对深度, 相对路径, 名称）升序（浅层优先）。"""
    _build_tree(tmp_path)
    listing = await list_subdirectories(str(tmp_path), "DEEP")
    depths = [
        0 if not e.rel_parent else (e.rel_parent or "").count("\\") + 1 for e in listing.entries
    ]
    assert depths == sorted(depths)
    assert depths[0] == 0  # 基准目录直接子级排在更深的命中之前
    assert listing.entries[0].name == "deep-root"


async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    _build_tree(tmp_path)
    listing = await list_subdirectories(str(tmp_path), "zzz-not-exist")
    assert listing.entries == ()
    assert listing.truncated is False


async def test_search_blank_query_falls_back_to_listing(tmp_path: Path) -> None:
    """空/纯空白 query 走一级列举（回归既有行为）。"""
    _build_tree(tmp_path)
    listing = await list_subdirectories(str(tmp_path), "   ")
    assert [e.name for e in listing.entries] == [
        "alpha",
        "deep-root",
        "Toolkit",
        "Works",
    ]  # 名称不区分大小写升序
    assert all(e.rel_parent is None for e in listing.entries)


async def test_search_truncates_by_hit_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """命中数达 MAX_BROWSE_ENTRIES 即截断（置 truncated）。"""
    import devprompt_ai.harness.browse as browse_module

    monkeypatch.setattr(browse_module, "MAX_BROWSE_ENTRIES", 2)
    for name in ("m1", "m2", "m3"):
        (tmp_path / name).mkdir()
    listing = await list_subdirectories(str(tmp_path), "m")
    assert len(listing.entries) == 2
    assert listing.truncated is True


async def test_search_truncates_by_depth_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """深度达 MAX_SEARCH_DEPTH 即停止（更深命中不返回，置 truncated）。"""
    import devprompt_ai.harness.browse as browse_module

    monkeypatch.setattr(browse_module, "MAX_SEARCH_DEPTH", 1)
    (tmp_path / "lvl1" / "match-deep").mkdir(parents=True)
    listing = await list_subdirectories(str(tmp_path), "match")
    assert listing.entries == ()
    assert listing.truncated is True


async def test_search_skips_unreadable_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不可读子目录被跳过，不中断整次搜索（同层其它命中仍返回）。"""
    (tmp_path / "match-a").mkdir()
    (tmp_path / "blocked").mkdir()
    (tmp_path / "blocked" / "match-b").mkdir()
    real_scandir = os.scandir

    def flaky(path: Any) -> Any:
        if str(path).endswith("blocked"):
            raise PermissionError(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky)  # browse 模块与本测试共用同一 os 模块对象
    listing = await list_subdirectories(str(tmp_path), "match")
    assert [e.name for e in listing.entries] == ["match-a"]
