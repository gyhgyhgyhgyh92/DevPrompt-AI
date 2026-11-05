"""纯回答模板（2026-11-05）：只解释，不产出方案。

与 a/b/c 三档模板的区别：那三个以「输出一套可直接复制的提示词」为目标，
本模板以「回答用户对已产出方案的追问」为目标，因此显式禁止重新组织方案正文。
"""

from __future__ import annotations

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.prompt_guard import build_evidence_block

SYSTEM = (
    "你是提示词优化师，此刻在回答用户对已产出方案的追问，而不是产出新方案。"
    "用简洁中文直接回答，可以引用上一轮方案的档位、标题与具体条目作为依据。"
    "禁止输出新的提示词正文，禁止重新组织方案，禁止说「以下是优化后的版本」。"
    "如果用户的问题需要改动方案，明确告诉他需要重新生成，不要自行修改。"
    "不知道就以取证结果为准说明不知道，不要编造文件路径或行号。只输出 JSON。"
)


def build_user(ctx: GenerationContext) -> str:
    """用户消息：证据经 JSON 块包裹 + 指令只在尾部（M-5）。"""
    evidence = build_evidence_block(
        {
            "用户追问": ctx.sentence,
            "上一轮方案": ctx.previous_variants or "（无，本轮之前还没有产出方案）",
            "推荐判定": ctx.ranking_summary or "（上一轮未打分或未推荐）",
            "取证摘要": ctx.facts_summary or "（无）",
            "已澄清信息": ctx.clarifications,
            "历史轮次": ctx.history_block or "（首轮，无历史）",
        }
    )
    return f'{evidence}\n请输出 JSON：{{"text": "你的回答"}}'
