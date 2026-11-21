"""目录型 Skill：frontmatter 解析、坏文件跳过、mtime 缓存。"""

from __future__ import annotations

from pathlib import Path

from devprompt_ai.harness.skills import loader


def _write_skill(root: Path, name: str, front: str, body: str = "正文内容") -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return path


def test_parse_frontmatter_with_and_without_block() -> None:
    meta, body = loader.parse_frontmatter("---\nname: a\ndescription: b\n---\nBODY")
    assert meta["name"] == "a" and meta["description"] == "b"
    assert body == "BODY"
    assert loader.parse_frontmatter("plain") == ({}, "plain")


def test_scan_reads_name_and_domains(tmp_path: Path) -> None:
    loader.invalidate_cache()
    _write_skill(tmp_path, "export", "name: 导出规范\ndescription: 统一出口\ndomains: code, work")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "SKILL.md").write_text("---\nname: 坏\n---\n", encoding="utf-8")

    metas = loader.scan([str(tmp_path)])
    names = {meta.name for meta in metas}
    assert "导出规范" in names
    meta = next(item for item in metas if item.name == "导出规范")
    assert meta.domains == ("code", "work")
    assert meta.source == "dir"


def test_scan_uses_cache_until_file_changes(tmp_path: Path, monkeypatch) -> None:
    loader.invalidate_cache()
    path = _write_skill(tmp_path, "cached", "name: 缓存技能")
    first = loader.scan([str(tmp_path)])
    assert len(first) == 1

    # 改内容但不改 mtime 摘要 → 命中缓存
    loader._cache[str(tmp_path)] = (loader._digest([path]), first)  # noqa: SLF001
    second = loader.scan([str(tmp_path)])
    assert second[0].name == "缓存技能"


def test_load_body_strips_frontmatter_and_truncates(tmp_path: Path) -> None:
    loader.invalidate_cache()
    _write_skill(tmp_path, "big", "name: 大技能", body="x" * (loader.MAX_BODY_CHARS + 100))
    meta = loader.scan([str(tmp_path)])[0]
    skill = loader.load_body(meta)
    assert "---" not in skill.body[:10]
    assert len(skill.body) <= loader.MAX_BODY_CHARS


def test_missing_dir_is_ignored() -> None:
    loader.invalidate_cache()
    assert loader.scan(["/no/such/dir"]) == []
