"""视觉生成包：文生图/图生图/文生视频提示词优化，无仓库上下文。

产出为可粘贴进 Midjourney/即梦/Sora 等工具的提示词文本；
风格细分（通用/摄影/创意/中文模型/JSON 结构化/视频）走
``domain.visual.style.*`` i18n 键，由生成层按 ``ctx.style_id`` 拼接。
"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack

#: 风格白名单（请求契约 ``style`` 字段的合法值；空串/缺省 = 通用风格）。
VISUAL_STYLES: Final[tuple[str, ...]] = (
    "general",
    "photography",
    "creative",
    "chinese-model",
    "json-structured",
    "video",
)


def visual_pack() -> DomainPack:
    return DomainPack(
        id="visual",
        needs_repo=False,
        allowed_actions=frozenset(
            {
                AgentAction.ASK,
                AgentAction.GENERATE,
                AgentAction.DELIVER,
                AgentAction.ABORT,
                AgentAction.REPLY,
            }
        ),
        claim_kinds=frozenset(),
        keywords=(
            "文生图",
            "生图",
            "画图",
            "绘图",
            "海报",
            "插画",
            "概念图",
            "示意图",
            "壁纸",
            "头像",
            "封面图",
            "配图",
            "logo",
            "图标",
            "图生图",
            "重绘",
            "扩图",
            "垫图",
            "midjourney",
            "mj提示词",
            "即梦",
            "sora",
            "可灵",
            "runway",
            "pixverse",
            "vidu",
            "文生视频",
            "生视频",
            "视频提示词",
            "运镜",
            "text2image",
            "image2image",
        ),
        name_key="domain.visual.name",
        directives_key="domain.visual.directives",
        sections_key="domain.visual.sections",
    )
