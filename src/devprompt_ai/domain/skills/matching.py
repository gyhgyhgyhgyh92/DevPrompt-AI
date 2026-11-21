"""Skill 匹配与预算挑选（纯函数，零 I/O）。

打分只看名称与描述（frontmatter 层），命中后才由调用方加载正文：
这样 100 个技能也不会把正文全塞进 prompt（渐进式披露）。
"""

from __future__ import annotations

from collections.abc import Sequence

from devprompt_ai.common.text import tokenize_sentence
from devprompt_ai.domain.skills.models import Skill, SkillMeta

#: 名称完全出现在原句里的权重；描述词命中每项权重。
_NAME_HIT = 3.0
_DESC_HIT = 0.8
_DOMAIN_HIT = 0.5
#: 低于该分数视为不相关，不注入——避免每轮都塞无关技能。
_MIN_SCORE = 0.8


def score_skill(meta: SkillMeta, sentence: str, domain: str = "") -> float:
    """按名称/描述/领域打分；停用或空名返回 0。"""
    if not meta.enabled or not meta.name.strip():
        return 0.0
    text = (sentence or "").lower()
    score = 0.0
    name = meta.name.strip().lower()
    if name and name in text:
        score += _NAME_HIT
    terms = {term for term in tokenize_sentence(meta.description) if len(term) > 1}
    if terms:
        hits = sum(1 for term in terms if term.lower() in text)
        score += _DESC_HIT * min(hits, 4)
    if domain and meta.domains and domain in meta.domains:
        score += _DOMAIN_HIT
    return score


def rank_skills(
    metas: Sequence[SkillMeta], sentence: str, domain: str = "", limit: int = 3
) -> list[tuple[float, SkillMeta]]:
    """按分数降序取前 N；同分按名称稳定排序（结果可复现）。"""
    scored = [(score_skill(meta, sentence, domain), meta) for meta in metas]
    relevant = [item for item in scored if item[0] >= _MIN_SCORE]
    relevant.sort(key=lambda item: (-item[0], item[1].name))
    return relevant[:limit]


def fit_skills(skills: Sequence[Skill], char_budget: int) -> tuple[list[Skill], bool]:
    """按给定顺序装入正文，超预算从低分项开始丢弃（调用方已按分数降序）。

    :returns: (选中的技能, 是否发生截断)
    """
    if char_budget <= 0:
        return [], bool(skills)
    kept: list[Skill] = []
    used = 0
    truncated = False
    for skill in skills:
        cost = len(skill.body) + len(skill.meta.name) + len(skill.meta.description) + 16
        if used + cost > char_budget:
            truncated = True
            continue
        kept.append(skill)
        used += cost
    return kept, truncated


def render_skills(skills: Sequence[Skill]) -> str:
    """拼成 system 里的技能块；无技能返回空串（调用方据此不加段落）。"""
    if not skills:
        return ""
    parts = [
        "## 可用技能（按需参考，不要逐条复述；与当前任务无关时忽略）",
    ]
    for skill in skills:
        head = f"### {skill.meta.name}"
        if skill.meta.description:
            head += f"：{skill.meta.description}"
        parts.append(head)
        if skill.body.strip():
            parts.append(skill.body.strip())
    return "\n\n".join(parts)
