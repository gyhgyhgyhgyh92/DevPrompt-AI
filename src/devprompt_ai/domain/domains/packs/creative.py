"""创意创作包：内容创作领域（文案/故事/脚本/命名等），无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def creative_pack() -> DomainPack:
    return DomainPack(
        id="creative",
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
            "口号",
            "slogan",
            "起名",
            "命名",
            "取名",
            "故事",
            "小说",
            "诗歌",
            "歌词",
            "头脑风暴",
            "创意",
            "广告语",
            "标题",
            "品牌故事",
        ),
        name_key="domain.creative.name",
        directives_key="domain.creative.directives",
        sections_key="domain.creative.sections",
    )
