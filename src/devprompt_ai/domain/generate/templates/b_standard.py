"""B 标准版模板（唯一常规出口）：含已定位符号路径，推断项显式标注。

2026-11-06 双语：文案在 ``common/i18n.py`` 的 ``template.*``。
2026-11-11 单套输出：C 档删除后，其「禁止编造锚点」与「原代码 → 新代码」两条硬性
要求并入本模板；正文统一按四段式组织。
2026-11-14 领域包：分段语义/硬规则/领域指令/claims 规则按 ``ctx.domain_id`` 切换；
code 域文案不变（零回归），通用域走 ``domain.*`` 键。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.domains import get_pack
from devprompt_ai.domain.domains.packs.visual import VISUAL_STYLES
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

#: 输出 JSON 骨架（单对象，无 level 字段）。
_JSON_SHAPE: str = (
    '{"title": "...", "body": "...", "changes": ["..."], '
    '"claims": [{"kind": "file|symbol|token|line|absence", "target": "...", '
    '"negates": "file|symbol|token|line|test"}]}'
)


def system_text(locale: Locale = DEFAULT_LOCALE, domain_id: str = "code") -> str:
    """SYSTEM 文案：分段语义与硬规则按领域包切换（code 复用既有文案，零回归）。"""
    pack = get_pack(domain_id)
    rules_key = "template.b.hard_rules" if domain_id == "code" else "template.b.hard_rules_generic"
    return tr("template.b.role", locale) + tr(rules_key, locale) + tr(pack.sections_key, locale)


#: 兼容旧引用（默认中文）。
SYSTEM = system_text()


def build_user(ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    pack = get_pack(ctx.domain_id)
    payload: dict[str, Any] = {
        tr("template.field.request", locale): ctx.sentence,
        tr("template.field.facts", locale): (
            ctx.facts_summary or tr("template.field.none_facts", locale)
        ),
        tr("template.field.clarifications", locale): ctx.clarifications,
        tr("template.field.conservative", locale): ctx.conservative,
        tr("template.field.excerpt", locale): (
            ctx.target_excerpt or tr("template.field.none_excerpt", locale)
        ),
        tr("template.field.design_tokens", locale): (
            "\n".join(ctx.design_tokens) or tr("template.field.none_design_tokens", locale)
        ),
        # 多轮（2026-10-20）：历史结论与记忆由 build_context 装配，缺省为空不出现
        tr("template.field.history", locale): (
            ctx.history_block or tr("template.field.none_history", locale)
        ),
        tr("template.field.memory", locale): (
            ctx.memory_block or tr("template.field.none_facts_plain", locale)
        ),
        # 多轮（2026-11-04）：上一轮方案正文，供「在已有方案上改」的轮次引用
        tr("template.field.previous_variants", locale): (
            ctx.previous_variants or tr("template.field.none_variants", locale)
        ),
    }
    # 领域指令（2026-11-14）：通用域注入术语/约束/交付标准；code 域无额外指令，
    # 连占位字段都不注入——保证 code 域 prompt 与领域化改造前逐字一致。
    # visual 域按 ctx.style_id 切风格指令（2026-11-14 多模态）；非法/缺省回退通用指令。
    if pack.directives_key:
        directives_key = pack.directives_key
        if ctx.domain_id == "visual" and ctx.style_id in VISUAL_STYLES:
            directives_key = f"domain.visual.style.{ctx.style_id}"
        payload[tr("template.field.domain", locale)] = tr(directives_key, locale)
    evidence = build_evidence_block(payload)
    claims_rules_key = (
        "template.claims_rules" if pack.claim_kinds else "template.claims_rules_generic"
    )
    return (
        f"{evidence}\n"
        f"{tr('template.instruction_prefix', locale)}"
        f"{_JSON_SHAPE}\n"
        f"{tr(claims_rules_key, locale)}"
    )
