"""学习教育包：课程/教案/复习计划/论文/考试辅导等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def learning_pack() -> DomainPack:
    return DomainPack(
        id="learning",
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
            "学习",
            "课程",
            "教案",
            "备课",
            "复习",
            "复习计划",
            "学习计划",
            "考试",
            "刷题",
            "讲解",
            "培训",
            "论文",
            "毕业",
            "答辩",
            "雅思",
            "托福",
            "考研",
            "习题",
            "知识点",
            "教学",
        ),
        name_key="domain.learning.name",
        directives_key="domain.learning.directives",
        sections_key="domain.learning.sections",
    )
