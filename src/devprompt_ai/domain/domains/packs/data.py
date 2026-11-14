"""数据分析包：数据清洗/统计/可视化/指标体系等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def data_pack() -> DomainPack:
    return DomainPack(
        id="data",
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
            "数据分析",
            "数据清洗",
            "统计",
            "可视化",
            "图表",
            "仪表盘",
            "漏斗",
            "留存",
            "转化率",
            "abtest",
            "a/b",
            "指标",
            "数据报告",
            "透视表",
        ),
        name_key="domain.data.name",
        directives_key="domain.data.directives",
        sections_key="domain.data.sections",
    )
