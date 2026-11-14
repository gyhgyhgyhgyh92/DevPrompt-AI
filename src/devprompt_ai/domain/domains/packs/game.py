"""游戏设计包：玩法策划/关卡/数值/剧情任务/规则设计等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def game_pack() -> DomainPack:
    return DomainPack(
        id="game",
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
            "游戏设计",
            "关卡",
            "数值策划",
            "玩法",
            "剧情线",
            "任务系统",
            "角色设定",
            "游戏策划",
            "桌游",
            "规则设计",
            "游戏文案",
            "怪物设计",
            "技能系统",
        ),
        name_key="domain.game.name",
        directives_key="domain.game.directives",
        sections_key="domain.game.sections",
    )
