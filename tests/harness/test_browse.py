"""harness/browse.py 单测：上级推导、仅列目录/排序、截断、错误码（F-601 页内浏览器数据源）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from devprompt_ai.domain.errors import RetrievalError
from devprompt_ai.harness.browse import (
    _list_drives_sync,
    _parent_of,
    list_subdirectories,
)


def test_parent_of_drive_root_returns_empty() -> None:
    """驱动器根：空串（回驱动器列表语义，前端据此决定「返回」目标）。"""
    assert _parent_of("D:\\") == ""
    assert _parent_of("C:\\") == ""


def test_parent_of_subdir_returns_parent() -> None:
    assert _parent_of("D:\\Works\\repo") == "D:\\Works"
    assert _parent_of("D:\\Works") == "D:\\"


async def test_list_subdirectories_only_dirs_sorted(tmp_path: Path) -> None:
    """仅列一级子目录（文件不列）且不区分大小写排序；path 为规范化绝对路径。"""
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "zeta").mkdir()
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    listing = await list_subdirectories(str(tmp_path))
    assert listing.path == str(tmp_path)
    assert [e.name for e in listing.entries] == ["Alpha", "beta", "zeta"]
    assert all(e.path.startswith(str(tmp_path)) for e in listing.entries)
    assert listing.truncated is False


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
    """超过上限：按名称序截断并置 truncated 标志（前端提示「仅显示前 N 项」）。"""
    import devprompt_ai.harness.browse as browse_module

    monkeypatch.setattr(browse_module, "MAX_BROWSE_ENTRIES", 2)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    listing = await list_subdirectories(str(tmp_path))
    assert [e.name for e in listing.entries] == ["a", "b"]
    assert listing.truncated is True


def test_list_drives_shape() -> None:
    """驱动器列表：path 空串 + parent None；条目形如 ``X:\\``（探测依赖真实盘符，仅验形状）。"""
    listing = _list_drives_sync()
    assert listing.path == ""
    assert listing.parent is None
    assert all(re.fullmatch(r"[A-Z]:\\", e.path) for e in listing.entries)
    assert all(e.name == e.path for e in listing.entries)
