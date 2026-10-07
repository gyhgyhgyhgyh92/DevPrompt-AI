"""C 档模板（F-304 初版）：完整路径 + 行号 + token 出处 + 边界预判。"""

from __future__ import annotations

import json

from devprompt_ai.domain.generate.ports import GenerationContext

SYSTEM = (
    "你是提示词优化师。取证已完成，输出激进版提示词：给出完整路径与行号、"
    "token 出处、边界预判（多状态/响应式/暗色/无障碍），并附显式测试指令。只输出 JSON。"
)


def build_user(ctx: GenerationContext) -> str:
    return (
        f"用户需求：{ctx.sentence}\n"
        f"取证摘要（含行号与 token 出处）：{ctx.facts_summary}\n"
        f"已澄清信息：{json.dumps(ctx.clarifications, ensure_ascii=False)}\n"
        f"保守模式：{ctx.conservative}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "C"}'
    )
