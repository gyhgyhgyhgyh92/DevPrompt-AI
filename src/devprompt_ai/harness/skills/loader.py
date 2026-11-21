"""目录型 Skill 扫描与解析（2026-11-21）：I/O 全在本模块，匹配逻辑在 domain。

格式兼容 Claude/CodeBuddy：`<dir>/<skill>/SKILL.md`，开头是 `---` 包裹的 frontmatter。
**不引 PyYAML**：只认 `name` / `description` / `domains` 三个键，其余行原样忽略——
技能正文才是内容，frontmatter 只承担「让模型和我都知道这是什么」的最小职责。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from devprompt_ai.domain.skills.models import Skill, SkillMeta

logger = logging.getLogger(__name__)

SKILL_FILENAME: Final[str] = "SKILL.md"
#: 正文上限：单个技能不该把预算吃光，超出截断并标注。
MAX_BODY_CHARS: Final[int] = 20_000
#: 扫描深度：`dir/skill/SKILL.md` 为主，允许 `dir/group/skill/SKILL.md`。
_MAX_DEPTH: Final[int] = 3

#: root → (mtime 摘要, 元数据列表)：目录没变就不重复解析。
_cache: dict[str, tuple[str, list[SkillMeta]]] = {}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆 frontmatter 与正文；无 frontmatter 时返回空字典 + 全文。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, body


def _meta_from_file(path: Path) -> SkillMeta | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.info("skill.read_failed", extra={"path": str(path)})
        return None
    front, _body = parse_frontmatter(text)
    name = front.get("name", "").strip() or path.parent.name
    if not name:
        return None
    domains = tuple(
        item.strip()
        for item in front.get("domains", "").replace("，", ",").split(",")
        if item.strip()
    )
    return SkillMeta(
        name=name,
        description=front.get("description", "").strip(),
        source="dir",
        path=str(path),
        domains=domains,
    )


def _digest(files: list[Path]) -> str:
    parts: list[str] = []
    for path in files:
        try:
            parts.append(f"{path}:{path.stat().st_mtime_ns}")
        except OSError:
            continue
    return "|".join(parts)


def scan(dirs: Sequence[str]) -> list[SkillMeta]:
    """扫描多个根目录；坏文件跳过（不因一个技能写错让整页崩）。"""
    metas: list[SkillMeta] = []
    for raw in dirs:
        root = Path(raw).expanduser()
        if not root.is_dir():
            continue
        files = sorted(
            path
            for path in root.rglob(SKILL_FILENAME)
            if len(path.relative_to(root).parts) - 1 <= _MAX_DEPTH
        )
        digest = _digest(files)
        cached = _cache.get(str(root))
        if cached is not None and cached[0] == digest:
            metas.extend(cached[1])
            continue
        found: list[SkillMeta] = []
        for file in files:
            meta = _meta_from_file(file)
            if meta is not None:
                found.append(meta)
        _cache[str(root)] = (digest, found)
        metas.extend(found)
    # 同名以先出现者为准，避免两个目录重复报同一技能。
    unique: dict[str, SkillMeta] = {}
    for meta in metas:
        unique.setdefault(meta.name.lower(), meta)
    return list(unique.values())


def load_body(meta: SkillMeta) -> Skill:
    """按需读取正文；目录来源读文件，自定义来源由调用方另行填充。"""
    if meta.source != "dir" or not meta.path:
        return Skill(meta=meta, body="")
    try:
        text = Path(meta.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Skill(meta=meta, body="")
    _front, body = parse_frontmatter(text)
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 1] + "…"
    return Skill(meta=meta, body=body)


def invalidate_cache() -> None:
    """测试与「重新扫描」按钮用。"""
    _cache.clear()
