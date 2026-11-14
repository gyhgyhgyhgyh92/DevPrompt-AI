"""金融财务包：财报/税务/报销/预算核算/投资分析等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def finance_pack() -> DomainPack:
    return DomainPack(
        id="finance",
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
            "财报",
            "资产负债",
            "现金流",
            "融资",
            "估值",
            "对账",
            "报销",
            "发票",
            "税务",
            "报税",
            "工资核算",
            "成本核算",
            "投资组合",
            "收益率",
            "记账",
            "预算表",
        ),
        name_key="domain.finance.name",
        directives_key="domain.finance.directives",
        sections_key="domain.finance.sections",
    )
