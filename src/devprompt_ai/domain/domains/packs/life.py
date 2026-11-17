"""生活事务包：个人生活领域（行程/采购/健身/搬家等），无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def life_pack() -> DomainPack:
    return DomainPack(
        id="life",
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
            "旅行",
            "出行",
            "行程",
            "攻略",
            "采购",
            "购物清单",
            "健身",
            "减脂",
            "食谱",
            "菜谱",
            "搬家",
            "日程",
            "作息",
            "收纳",
            "装修",
            "维修",
            "保险",
        ),
        name_key="domain.life.name",
        directives_key="domain.life.directives",
        sections_key="domain.life.sections",
    )
