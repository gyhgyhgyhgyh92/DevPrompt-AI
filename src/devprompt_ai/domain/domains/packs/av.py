"""音视频脚本包：视频脚本/分镜/口播稿/播客脚本等，无仓库上下文。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack


def av_pack() -> DomainPack:
    return DomainPack(
        id="av",
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
            "剧本",
            "脚本",
            "分镜",
            "口播",
            "旁白",
            "字幕",
            "视频脚本",
            "vlog",
            "播客",
            "直播脚本",
            "剪辑",
            "拍摄",
            "配音",
            "短视频",
        ),
        name_key="domain.av.name",
        directives_key="domain.av.directives",
        sections_key="domain.av.sections",
    )
