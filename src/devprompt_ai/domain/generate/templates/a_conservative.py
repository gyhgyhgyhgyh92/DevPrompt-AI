"""A 档模板（F-302 初版）：只述意图 + 待确认清单，不编造路径行号。"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

SYSTEM = (
    "你是提示词优化师。信息有限，输出保守版提示词：只陈述用户意图与可执行要点，"
    "禁止编造文件路径、行号、token 名；结尾必须列出待确认清单。只输出 JSON。"
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
