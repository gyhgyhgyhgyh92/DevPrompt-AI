"""A 档模板（F-302 初版）：只述意图 + 待确认清单，不编造路径行号。

2026-11-06 双语：SYSTEM 与证据字段名按 locale 取（``common/i18n.py`` 的 ``template.*``），
默认 zh-CN 与旧版逐字一致。
"""

from __future__ import annotations

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block


def system_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("template.a.role", locale) + tr("template.body_semantics", locale)


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
        }
    )
    return (
        f"{evidence}\n"
        f"{tr('template.instruction_prefix', locale)}"
        '{"title": "...", "body": "...", "changes": ["..."], "level": "A"}'
    )
