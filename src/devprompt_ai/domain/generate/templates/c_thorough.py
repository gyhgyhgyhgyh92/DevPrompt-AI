"""C 档模板（F-304 初版）：完整路径 + 行号 + token 出处 + 边界预判。

2026-11-06 双语：同 A 档；可验证锚点声明也走语言包（``template.c.anchor``）。
"""

from __future__ import annotations

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block


def system_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return (
        tr("template.c.role", locale)
        + tr("template.body_semantics", locale)
        + tr("template.c.anchor", locale)
    )


#: 兼容旧引用（默认中文）。
SYSTEM = system_text()


def build_user(ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    evidence = build_evidence_block(
        {
            tr("template.field.request", locale): ctx.sentence,
            tr("template.field.facts_c", locale): ctx.facts_summary,
            tr("template.field.clarifications", locale): ctx.clarifications,
            tr("template.field.conservative", locale): ctx.conservative,
        }
    )
    return (
        f"{evidence}\n"
        f"{tr('template.instruction_prefix', locale)}"
        '{"title": "...", "body": "...", "changes": ["..."], "level": "C"}'
    )
