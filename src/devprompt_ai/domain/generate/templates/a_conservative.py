"""A 档模板（F-302 初版）：只述意图 + 待确认清单，不编造路径行号。"""

from __future__ import annotations

import json

from devprompt_ai.domain.generate.ports import GenerationContext

SYSTEM = (
    "你是提示词优化师。信息有限，输出保守版提示词：只陈述用户意图与可执行要点，"
    "禁止编造文件路径、行号、token 名；结尾必须列出待确认清单。只输出 JSON。"
)


def build_user(ctx: GenerationContext) -> str:
    return (
        f"用户需求：{ctx.sentence}\n"
        f"已澄清信息：{json.dumps(ctx.clarifications, ensure_ascii=False)}\n"
        f"取证摘要：{ctx.facts_summary or '（无，禁止编造路径）'}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "A"}'
    )
