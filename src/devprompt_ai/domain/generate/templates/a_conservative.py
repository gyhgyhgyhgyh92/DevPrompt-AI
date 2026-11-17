"""A 保守版模板：只述意图 + 待确认清单，不编造路径行号。

**本模板仅用于异常兜底**（2026-11-11）：主流程抛错或产出无效时降级重试一次，
正常轮次不得使用。

2026-11-06 双语：SYSTEM 与证据字段名按 locale 取（``common/i18n.py`` 的 ``template.*``），
默认 zh-CN 与旧版逐字一致。
2026-11-14 领域包：通用域兜底时分段语义走 ``domain.*`` 键（A 的代码式四段对通用域无效）；
code 域文案不变。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.domains import get_pack
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

#: 输出 JSON 骨架（单对象，无 level 字段）。
_JSON_SHAPE: str = (
    '{"title": "...", "body": "...", "changes": ["..."], '
    '"claims": [{"kind": "file|symbol|token|line|absence", "target": "...", '
    '"negates": "file|symbol|token|line|test"}]}'
)


def system_text(locale: Locale = DEFAULT_LOCALE, domain_id: str = "code") -> str:
    """SYSTEM 文案：通用域兜底直接用该领域四段式（无代码概念）；code 域逐字不变。"""
    pack = get_pack(domain_id)
    sections = (
        tr("template.body_semantics", locale) + tr("template.sections.a", locale)
        if domain_id == "code"
        else tr(pack.sections_key, locale)
    )
    return tr("template.a.role", locale) + tr("template.a.fallback_only", locale) + sections


#: 兼容旧引用（默认中文）。
SYSTEM = system_text()


def build_user(ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    pack = get_pack(ctx.domain_id)
    payload: dict[str, Any] = {
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
    # 领域指令（2026-11-14）：与 b_standard 同策略，code 域 prompt 逐字不变。
    if pack.directives_key:
        payload[tr("template.field.domain", locale)] = tr(pack.directives_key, locale)
    evidence = build_evidence_block(payload)
    claims_rules_key = (
        "template.claims_rules" if pack.claim_kinds else "template.claims_rules_generic"
    )
    return (
        f"{evidence}\n"
        f"{tr('template.instruction_prefix', locale)}"
        f"{_JSON_SHAPE}\n"
        f"{tr(claims_rules_key, locale)}\n"
        f"{tr('template.a.fallback_only', locale)}"
    )
