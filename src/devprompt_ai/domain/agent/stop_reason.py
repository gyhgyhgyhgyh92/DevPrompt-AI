"""结构化终止原因（移植天枢 stop-reason.ts）。

为什么要枚举而不是自由文本：长会话里「为什么停」是运维第一问题——
模型自愿收尾、守卫熔断、用户中断、故障必须可区分，否则误熔断无法归因。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class StopReason(str, Enum):
    NATURAL_FINISH = "natural-finish"
    NO_ANSWER = "no-answer"
    END_TURN = "end-turn"
    #: 执行已结束但流程在等用户答复（ask/guardrail），不是业务完成。
    AWAIT_USER = "await-user"
    GOAL_ROLLOVER = "goal-rollover"
    CONVERGENCE_ABORT = "convergence-abort"
    NO_TOOL_ABORT = "no-tool-abort"
    WATCHDOG_STALL = "watchdog-stall"
    MAX_TURNS = "max-turns"
    WEDGED_LOOP = "wedged-loop"
    USER_INTERRUPT = "user-interrupt"
    STREAM_ERROR = "stream-error"
    CHECKPOINT = "checkpoint"


#: 守卫触发（非模型自愿）：这类停止需要额外解释给用户。
GUARD_REASONS: Final[frozenset[StopReason]] = frozenset(
    {
        StopReason.CONVERGENCE_ABORT,
        StopReason.NO_TOOL_ABORT,
        StopReason.WATCHDOG_STALL,
        StopReason.MAX_TURNS,
        StopReason.WEDGED_LOOP,
    }
)

#: 模型自愿收尾。
VOLUNTARY_REASONS: Final[frozenset[StopReason]] = frozenset(
    {StopReason.NATURAL_FINISH, StopReason.END_TURN}
)

#: 非终态：checkpoint 之后仍会继续。
NON_TERMINAL_REASONS: Final[frozenset[StopReason]] = frozenset({StopReason.CHECKPOINT})


@dataclass(frozen=True, slots=True)
class StopRecord:
    """一次终止的结构化记录，可直出事件/日志。"""

    reason: StopReason
    detail: str = ""

    @property
    def is_guard(self) -> bool:
        return self.reason in GUARD_REASONS

    @property
    def is_voluntary(self) -> bool:
        return self.reason in VOLUNTARY_REASONS

    @property
    def is_terminal(self) -> bool:
        return self.reason not in NON_TERMINAL_REASONS


def snapshot_stop_reason(status: str, state: str = "") -> StopReason:
    """把流程快照映射为终止原因（runtime 收尾时使用）。"""
    if status == "aborted" or state == "ABORTED":
        return StopReason.USER_INTERRUPT
    if status == "ask" or status == "guardrail":
        return StopReason.AWAIT_USER
    if status == "done" or state == "DONE":
        return StopReason.NATURAL_FINISH
    return StopReason.NATURAL_FINISH
