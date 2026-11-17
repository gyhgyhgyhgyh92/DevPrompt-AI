"""索引器测试：扫描、符号落库、导入边与影响半径。"""

from __future__ import annotations

from pathlib import Path

from devprompt_ai.harness.repo_indexer import collect_python_files, impact_for, index_project


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("from pkg.mod import f\n", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "skip.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_collect_skips_vendor_dirs(tmp_path: Path) -> None:
    root = _project(tmp_path)

    files = collect_python_files(str(root))

    assert "pkg/mod.py" in files
    assert "broken.py" in files
    assert all("node_modules" not in item for item in files)


async def test_index_project_records_symbols_and_edges(tmp_path: Path) -> None:
    root = _project(tmp_path)
    db = str(tmp_path / "index.db")

    indexed, failed = await index_project(db, str(root))

    assert indexed == 2, "pkg/__init__.py 与 pkg/mod.py 成功"
    assert failed == 1, "语法错误文件只计数、不阻断"

    impact = await impact_for(db, str(root), "pkg/mod.py")
    assert impact.get("pkg/__init__.py") == 1


async def test_index_is_idempotent(tmp_path: Path) -> None:
    root = _project(tmp_path)
    db = str(tmp_path / "index.db")

    first = await index_project(db, str(root))
    second = await index_project(db, str(root))

    assert first == second
    assert (await impact_for(db, str(root), "pkg/mod.py")) == {"pkg/__init__.py": 1}
