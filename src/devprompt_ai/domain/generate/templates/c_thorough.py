"""C 档模板（F-304 初版）：完整路径 + 行号 + token 出处 + 边界预判。"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import VERIFIABLE_ANCHOR_C, build_evidence_block

SYSTEM = (
    "你是提示词优化师。取证已完成，输出激进版提示词：给出完整路径与行号、"
    "token 出处、边界预判（多状态/响应式/暗色/无障碍），并附显式测试指令。只输出 JSON。\n"
    f"{VERIFIABLE_ANCHOR_C}"
)


def build_user(ctx: GenerationContext) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    evidence = build_evidence_block(
        {
            "用户需求": ctx.sentence,
            "取证摘要（含行号与 token 出处）": ctx.facts_summary,
            "已澄清信息": ctx.clarifications,
            "保守模式": ctx.conservative,
        }
    )
    return (
        f"{evidence}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "C"}'
    )
