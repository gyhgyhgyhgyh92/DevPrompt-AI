"""文案营销包：营销文案/投放策划/社媒内容/增长方案等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def marketing_pack() -> DomainPack:
    return DomainPack(
        id="marketing",
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
            "营销",
            "文案",
            "投放",
            "广告",
            "获客",
            "私域",
            "公众号",
            "小红书",
            "抖音",
            "种草",
            "海报",
            "裂变",
            "增长",
            "品牌策划",
            "促销文案",
        ),
        name_key="domain.marketing.name",
        directives_key="domain.marketing.directives",
        sections_key="domain.marketing.sections",
    )
