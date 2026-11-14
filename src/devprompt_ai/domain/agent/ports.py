"""Agent 决策端口（MUST-06：domain 只声明能力，实现由 decision/fallback.py 注入）。

与 ``DecisionPort`` 的分工：后者回答「这组候选怎么排 / 这份取证怎么判 / 这几套方案怎么打分」，
``ActionPlanner`` 回答「本轮下一步该做什么」。两者共用同一 LLM 实现（MUST-12）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from devprompt_ai.domain.agent.action import AgentStep
from devprompt_ai.domain.decision.port import NextActionOutput
from devprompt_ai.domain.models import FactResult


@runtime_checkable
class ActionPlanner(Protocol):
    """决定 agentic 循环的下一步动作。"""

    async def next_action(
        self,
        *,
        sentence: str,
        facts: Sequence[FactResult],
        steps: Sequence[AgentStep],
        variant_count: int,
        clarifications: Mapping[str, str],
        correction: str = "",
        inherited_variant_count: int = 0,
    ) -> NextActionOutput:
        """返回下一个动作及其理由。

        ``steps`` 是本轮已执行的动作序列，供模型判断「是不是在原地打转」；
        ``variant_count`` 为可用方案套数（0 表示尚未生成）。
        ``inherited_variant_count`` 为其中**继承自上一轮**的套数（2026-11-11）：
        它让调度层能区分「本轮已按指令生成」与「手里只有上一轮的旧方案」——
        后者遇到新的修改要求时必须重新 generate，不能直接 deliver 旧内容。
        ``correction`` 是外环给出的本轮纠偏提示（空串表示无），只影响措辞不改动作枚举。
        """
        ...
