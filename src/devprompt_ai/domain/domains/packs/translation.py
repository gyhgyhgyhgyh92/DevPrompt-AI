"""翻译本地化包：多语言翻译/本地化改写/术语表等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def translation_pack() -> DomainPack:
    return DomainPack(
        id="translation",
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
            "翻译",
            "译成",
            "中译英",
            "英译中",
            "本地化",
            "多语言",
            "译文",
            "译稿",
            "校对译文",
            "translate",
        ),
        name_key="domain.translation.name",
        directives_key="domain.translation.directives",
        sections_key="domain.translation.sections",
    )
