"""B 档模板（F-303 初版）：含已定位符号路径，推断项显式标注。"""

from __future__ import annotations

import json

from devprompt_ai.domain.generate.ports import GenerationContext

SYSTEM = (
    "你是提示词优化师。基于已定位的符号路径输出标准版提示词：路径可追溯，"
    "推断项必须以「（推断）」标注，禁止编造未提供的行号。只输出 JSON。"
)


def build_user(ctx: GenerationContext) -> str:
    return (
        f"用户需求：{ctx.sentence}\n"
        f"取证摘要：{ctx.facts_summary}\n"
        f"已澄清信息：{json.dumps(ctx.clarifications, ensure_ascii=False)}\n"
        '请输出 JSON：{"title": "...", "body": "...", "changes": ["..."], "level": "B"}'
    )
