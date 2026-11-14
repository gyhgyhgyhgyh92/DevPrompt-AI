"""运营策划包：活动策划/社群运营/用户增长/内容排期等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def operations_pack() -> DomainPack:
    return DomainPack(
        id="operations",
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
            "运营",
            "活动策划",
            "社群",
            "用户增长",
            "留存运营",
            "内容排期",
            "活动方案",
            "促销活动",
            "用户分层",
            "会员体系",
            "冷启动",
            "拉新活动",
        ),
        name_key="domain.operations.name",
        directives_key="domain.operations.directives",
        sections_key="domain.operations.sections",
    )
