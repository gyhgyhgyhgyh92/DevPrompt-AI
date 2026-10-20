"""A 档模板（F-302 初版）：只述意图 + 待确认清单，不编造路径行号。"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

SYSTEM = (
    "你是提示词优化师。信息有限，输出保守版提示词：只陈述用户意图与可执行要点，"
    "禁止编造文件路径、行号、token 名；结尾必须列出待确认清单。只输出 JSON。"
    "\n\n【body 的语义（2026-10-20 起强制）】body 必须是可直接复制给 Agent 执行的提示词正文："
    "包含角色与目标、上下文（文件/符号/行号，只能用已提供的）、必须遵守的约束、期望的输出格式。"
    "禁止出现「建议」「为什么这样改」「本方案改动如下」「以下是我的优化」等元叙述；"
    "不要复述取证过程；不要写实施方案之外的客套话。"
    "改动了哪几处只写在 changes 数组里，不得混进 body。"
)


def build_user(ctx: GenerationContext) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    evidence = build_evidence_block(
        {
            "用户需求": ctx.sentence,
            "已澄清信息": ctx.clarifications,
            "取证摘要": ctx.facts_summary or "（无，禁止编造路径）",
            "保守模式": ctx.conservative,
        }
    )
    return (
        f"{evidence}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "A"}'
    )
