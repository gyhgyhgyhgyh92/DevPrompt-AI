"""A 保守版模板：只述意图 + 待确认清单，不编造路径行号。

**本模板仅用于异常兜底**（2026-11-11）：主流程抛错或产出无效时降级重试一次，
正常轮次不得使用。

2026-11-06 双语：SYSTEM 与证据字段名按 locale 取（``common/i18n.py`` 的 ``template.*``），
默认 zh-CN 与旧版逐字一致。
"""

from __future__ import annotations

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

#: 输出 JSON 骨架（单对象，无 level 字段）。
_JSON_SHAPE: str = (
    '{"title": "...", "body": "...", "changes": ["..."], '
    '"claims": [{"kind": "file|symbol|token|line|absence", "target": "...", '
    '"negates": "file|symbol|token|line|test"}]}'
)


def system_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return (
        tr("template.a.role", locale)
        + tr("template.a.fallback_only", locale)
        + tr("template.body_semantics", locale)
        + tr("template.sections.a", locale)
    )


#: 兼容旧引用（默认中文）。
SYSTEM = system_text()


def build_user(ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    evidence = build_evidence_block(
        {
            tr("template.field.request", locale): ctx.sentence,
            tr("template.field.clarifications", locale): ctx.clarifications,
            tr("template.field.facts", locale): (
                ctx.facts_summary or tr("template.field.none_facts", locale)
            ),
            tr("template.field.conservative", locale): ctx.conservative,
            tr("template.field.excerpt", locale): (
                ctx.target_excerpt or tr("template.field.none_excerpt", locale)
            ),
            tr("template.field.design_tokens", locale): (
                "\n".join(ctx.design_tokens) or tr("template.field.none_design_tokens", locale)
            ),
            tr("template.field.history", locale): (
                ctx.history_block or tr("template.field.none_history", locale)
            ),
            tr("template.field.memory", locale): (
                ctx.memory_block or tr("template.field.none_facts_plain", locale)
            ),
            tr("template.field.previous_variants", locale): (
                ctx.previous_variants or tr("template.field.none_variants", locale)
            ),
        }
    )
    return (
        f"{evidence}\n"
        f"{tr('template.instruction_prefix', locale)}"
        f"{_JSON_SHAPE}\n"
        f"{tr('template.claims_rules', locale)}\n"
        f"{tr('template.a.fallback_only', locale)}"
    )
