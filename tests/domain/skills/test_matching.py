"""Skill 匹配与预算挑选（纯函数）。"""

from __future__ import annotations

from devprompt_ai.domain.skills.matching import (
    fit_skills,
    rank_skills,
    render_skills,
    score_skill,
)
from devprompt_ai.domain.skills.models import Skill, SkillMeta


def _meta(name: str, desc: str = "", domains: tuple[str, ...] = ()) -> SkillMeta:
    return SkillMeta(name=name, description=desc, domains=domains)


def test_name_hit_beats_description_hit() -> None:
    named = score_skill(_meta("组件导出规范", "导出组件时统一出口"), "请按组件导出规范新增页面")
    described = score_skill(_meta("其他", "新增页面时导出组件"), "请按组件导出规范新增页面")
    assert named > described


def test_disabled_and_unrelated_are_dropped() -> None:
    metas = [
        _meta("停用技能"),
        SkillMeta(name="启用技能", description="新增页面", enabled=False),
        _meta("无关技能", "量子计算"),
    ]
    assert rank_skills(metas, "新增页面") == []


def test_domain_match_adds_score() -> None:
    base = _meta("前端规范", "页面")
    with_domain = SkillMeta(name="前端规范", description="页面", domains=("code",))
    assert score_skill(with_domain, "页面", "code") > score_skill(base, "页面", "code")


def test_fit_skills_respects_budget() -> None:
    metas = [Skill(meta=_meta(f"s{i}"), body="x" * 100) for i in range(5)]
    kept, truncated = fit_skills(metas, char_budget=250)
    assert len(kept) == 2
    assert truncated is True
    empty, _ = fit_skills(metas, char_budget=0)
    assert empty == []


def test_render_skills_empty_returns_blank() -> None:
    assert render_skills([]) == ""
    block = render_skills([Skill(meta=_meta("规范", "说明"), body="正文")])
    assert "### 规范" in block and "正文" in block
