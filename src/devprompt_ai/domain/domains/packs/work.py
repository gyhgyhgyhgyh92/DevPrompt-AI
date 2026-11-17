"""工作事务包：办公任务领域（周报/汇报/文档/数据分析等），无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def work_pack() -> DomainPack:
    return DomainPack(
        id="work",
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
            "周报",
            "日报",
            "汇报",
            "总结",
            "述职",
            "复盘",
            "会议纪要",
            "纪要",
            "邮件",
            "文档",
            "工作方案",
            "工作计划",
            "报告",
            "ppt",
            "制度",
            "流程",
            "排期",
            "okr",
        ),
        name_key="domain.work.name",
        directives_key="domain.work.directives",
        sections_key="domain.work.sections",
    )
