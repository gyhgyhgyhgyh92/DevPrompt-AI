"""医疗健康包：症状梳理/就医准备/康复随访记录等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def medical_pack() -> DomainPack:
    return DomainPack(
        id="medical",
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
            "症状",
            "用药",
            "处方",
            "诊断",
            "病历",
            "康复",
            "随访",
            "慢病",
            "挂号",
            "问诊",
            "体检",
            "就医",
            "就诊",
            "病史",
        ),
        name_key="domain.medical.name",
        directives_key="domain.medical.directives",
        sections_key="domain.medical.sections",
    )
