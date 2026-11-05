"""Agent 动作、步骤与预算（纯数据，零 I/O，MUST-06）。

星型状态机里 AGENTIC 是决策态：每完成一个动作回到它，由 ``ActionPlanner`` 决定下一步。
本模块只描述「有哪些动作、一步长什么样、预算多少」，不关心动作怎么执行——
执行与状态转移在 ``service.run_agent_loop``。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

#: 单轮 agentic 循环的硬上限。取 24 是因为一次完整交付实测不超过 8 步，
#: 24 留三倍余量；超过即视为病态循环，由收敛检测兜底而非靠这个数。
MAX_AGENT_STEPS: Final[int] = 24


class AgentAction(str, Enum):
    """模型可选的下一步动作。"""

    RETRIEVE = "retrieve"
    PROBE = "probe"
    ASK = "ask"
    GENERATE = "generate"
    RANK = "rank"
    DELIVER = "deliver"
    ABORT = "abort"
    #: 纯回答（2026-11-05）：只产出文字，不生成方案、不改档位、不改取证。
    #: 用于「为什么选 B」「两套差异是什么」这类讨论性追问——此前所有动作都会
    #: 改动状态，导致这类追问只能把上一轮方案原样返回。
    REPLY = "reply"


#: 终结动作：执行后循环立即结束，不再回到 AGENTIC。
#: reply 与 deliver 的区别：deliver 交付方案，reply 只回答，不产出 variants。
TERMINAL_ACTIONS: Final[frozenset[AgentAction]] = frozenset(
    {AgentAction.DELIVER, AgentAction.ABORT, AgentAction.REPLY}
)


class StepOutcome(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AgentStep:
    """一次动作执行的可观测记录。字段全部为原始值，便于 JSON 落库。"""

    index: int
    action: AgentAction
    outcome: StepOutcome
    duration_ms: int
    #: 本步结束后通过的事实数，用于「证据停滞」判据
    facts_passed: int
    #: 本步决策是否由实测置信度支撑；False 表示模型未给判断（no_data）
    decided_by_evidence: bool = True
    note: str = ""


@dataclass(frozen=True, slots=True)
class AgentBudget:
    """循环预算。步数是唯一硬约束，成本由既有护栏单独管（MUST-26）。"""

    max_steps: int = MAX_AGENT_STEPS

    def is_exhausted(self, steps: Sequence[AgentStep]) -> bool:
        return len(steps) >= self.max_steps
