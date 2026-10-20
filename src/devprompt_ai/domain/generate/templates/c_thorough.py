"""C 档模板（F-304 初版）：完整路径 + 行号 + token 出处 + 边界预判。"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import VERIFIABLE_ANCHOR_C, build_evidence_block

SYSTEM = (
    "你是提示词优化师。取证已完成，输出激进版提示词：给出完整路径与行号、"
    "token 出处、边界预判（多状态/响应式/暗色/无障碍），并附显式测试指令。只输出 JSON。"
    "\n\n【body 的语义（2026-10-20 起强制）】body 必须是可直接复制给 Agent 执行的提示词正文："
    "包含角色与目标、上下文（文件/符号/行号，只能用已提供的）、必须遵守的约束、期望的输出格式。"
    "禁止出现「建议」「为什么这样改」「本方案改动如下」「以下是我的优化」等元叙述；"
    "不要复述取证过程；不要写实施方案之外的客套话。"
    "改动了哪几处只写在 changes 数组里，不得混进 body。"
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
