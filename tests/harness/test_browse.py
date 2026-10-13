"""harness/browse.py 单测：条目元数据/排序、上级推导、截断、错误码。

F-601 页内文件资源管理器数据源（GET /project/browse）。
"""

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

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def test_parent_of_drive_root_returns_empty() -> None:
    """驱动器根：空串（回驱动器列表语义，前端据此决定「返回」目标）。"""
    assert _parent_of("D:\\") == ""
    assert _parent_of("C:\\") == ""


def test_parent_of_subdir_returns_parent() -> None:
    assert _parent_of("D:\\Works\\repo") == "D:\\Works"
    assert _parent_of("D:\\Works") == "D:\\"


async def test_list_entries_dirs_before_files_with_metadata(tmp_path: Path) -> None:
    """目录在前、文件在后（各自名称升序）；文件含真实 size 与 ISO 修改时间；目录 size=None。"""
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "zeta").mkdir()
    (tmp_path / "note.txt").write_bytes(b"hello")
    (tmp_path / "a.md").write_bytes(b"x" * 1536)

    listing = await list_subdirectories(str(tmp_path))

    assert listing.path == str(tmp_path)
    assert listing.truncated is False
    assert [e.name for e in listing.entries] == ["Alpha", "beta", "zeta", "a.md", "note.txt"]
    assert [e.kind for e in listing.entries] == ["dir"] * 3 + ["file"] * 2
    for e in listing.entries:
        assert e.path.startswith(str(tmp_path))
        assert e.modified_at is not None and _ISO_RE.match(e.modified_at) is not None
    files = {e.name: e for e in listing.entries if e.kind == "file"}
    assert all(e.size is None for e in listing.entries if e.kind == "dir")
    assert files["note.txt"].size == 5
    assert files["a.md"].size == 1536


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
    """超过上限：按既定序（目录在前）截断并置 truncated 标志（前端提示）。"""
    import devprompt_ai.harness.browse as browse_module

    monkeypatch.setattr(browse_module, "MAX_BROWSE_ENTRIES", 2)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    listing = await list_subdirectories(str(tmp_path))
    assert [e.name for e in listing.entries] == ["a", "b"]
    assert listing.truncated is True


def test_list_drives_shape() -> None:
    """驱动器列表：path 空串 + parent None；条目 kind=dir 且无元数据。

    探测依赖真实盘符，仅验证形状。
    """
    listing = _list_drives_sync()
    assert listing.path == ""
    assert listing.parent is None
    assert all(re.fullmatch(r"[A-Z]:\\", e.path) for e in listing.entries)
    assert all(
        e.kind == "dir" and e.size is None and e.modified_at is None for e in listing.entries
    )
