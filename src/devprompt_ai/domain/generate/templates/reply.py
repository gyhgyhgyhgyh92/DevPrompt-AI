"""纯回答模板（2026-11-05）：只解释，不产出方案。

与 a/b/c 三档模板的区别：那三个以「输出一套可直接复制的提示词」为目标，
本模板以「回答用户对已产出方案的追问」为目标，因此显式禁止重新组织方案正文。

2026-11-06 双语：文案在 ``common/i18n.py`` 的 ``template.reply.*`` 与 ``template.field.*``。
"""

from __future__ import annotations

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block


def system_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("template.reply.role", locale)


#: 兼容旧引用（默认中文）。
SYSTEM = system_text()


def build_user(ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
    """用户消息：证据经 JSON 块包裹 + 指令只在尾部（M-5）。"""
    evidence = build_evidence_block(
        {
            tr("template.field.followup", locale): ctx.sentence,
            tr("template.field.previous_variants", locale): (
                ctx.previous_variants or tr("template.field.none_variants", locale)
            ),
            tr("template.field.ranking", locale): (
                ctx.ranking_summary or tr("template.field.none_ranking", locale)
            ),
            tr("template.field.facts", locale): (
                ctx.facts_summary or tr("template.field.none_facts_plain", locale)
            ),
            tr("template.field.clarifications", locale): ctx.clarifications,
            tr("template.field.history", locale): (
                ctx.history_block or tr("template.field.none_history", locale)
            ),
        }
    )
    return f'{evidence}\n{tr("template.instruction_prefix", locale)}{{"text": "your answer"}}'
