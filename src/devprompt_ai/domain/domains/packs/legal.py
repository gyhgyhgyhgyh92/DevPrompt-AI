"""法律合同包：合同/协议/合规审查/法律文书等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def legal_pack() -> DomainPack:
    return DomainPack(
        id="legal",
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
            "合同",
            "协议",
            "条款",
            "法务",
            "合规",
            "纠纷",
            "诉讼",
            "仲裁",
            "授权书",
            "免责",
            "律师",
            "违约",
            "法律",
        ),
        name_key="domain.legal.name",
        directives_key="domain.legal.directives",
        sections_key="domain.legal.sections",
    )
