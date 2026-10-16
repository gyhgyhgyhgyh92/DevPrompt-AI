"""B 档模板（F-303 初版）：含已定位符号路径，推断项显式标注。"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

SYSTEM = (
    "你是提示词优化师。基于已定位的符号路径输出标准版提示词：路径可追溯，"
    "推断项必须以「（推断）」标注，禁止编造未提供的行号。只输出 JSON。"
)


def build_user(ctx: GenerationContext) -> str:
    """用户消息：证据经 JSON 块包裹 + 安全声明（M-5），指令只在尾部。"""
    evidence = build_evidence_block(
        {
            "用户需求": ctx.sentence,
            "取证摘要": ctx.facts_summary,
            "已澄清信息": ctx.clarifications,
            "保守模式": ctx.conservative,
        }
    )
    return (
        f"{evidence}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "B"}'
    )
