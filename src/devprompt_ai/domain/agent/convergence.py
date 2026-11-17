"""Agentic 循环的三判据收敛检测（纯函数，零 I/O，MUST-06）。

只保留三条在「单轮内多步动作」场景下有真实含义的判据，不做 Tianshu 的七信号:

1. 动作重复——连续多步同一 action 且 outcome 相同，说明原地打转；
2. 证据停滞——``facts_passed`` 连续多步无增长，说明检索/取证没带来新信息；
3. 决策无依据——连续多步 ``decided_by_evidence=False``，说明模型在无实测支撑下推进。

三条取或。分级遵循「先警告后熔断」：L3 必须存在 L2 记录，否则降级为 L2——
没有预警过的熔断无法向用户解释。步数不足时返回 L0（缺数据不冒充停滞信号）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from devprompt_ai.domain.agent.action import AgentStep

#: 连续「同动作 + 同结果」的告警/熔断步数
REPEAT_WARN_STEPS: Final[int] = 3
REPEAT_ABORT_STEPS: Final[int] = 5
#: 事实无增长 / 决策无依据 的告警/熔断步数
STALL_WARN_STEPS: Final[int] = 6
STALL_ABORT_STEPS: Final[int] = 12
#: 低于此步数不做判定：三判据都需要窗口，样本不足时不误报
MIN_STEPS_FOR_JUDGEMENT: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ConvergenceVerdict:
    """一次收敛判定结果。level 0 表示一切正常。"""

    level: Literal[0, 1, 2, 3]
    reason: str
    should_abort: bool


NO_STALL: Final[ConvergenceVerdict] = ConvergenceVerdict(level=0, reason="", should_abort=False)


def _trailing_repeat_steps(steps: Sequence[AgentStep]) -> int:
    """末尾连续「同动作 + 同结果」的步数（含最后一步）。"""
    if not steps:
        return 0
    last = steps[-1]
    count = 0
    for step in reversed(steps):
        if step.action is not last.action or step.outcome is not last.outcome:
            break
        count += 1
    return count


def _steps_without_fact_gain(steps: Sequence[AgentStep]) -> int:
    """末尾连续保持同一 ``facts_passed`` 的步数。"""
    if not steps:
        return 0
    tail = steps[-1].facts_passed
    count = 0
    for step in reversed(steps):
        if step.facts_passed != tail:
            break
        count += 1
    return count


def _steps_without_evidence(steps: Sequence[AgentStep]) -> int:
    """末尾连续「无实测依据决策」的步数。"""
    count = 0
    for step in reversed(steps):
        if step.decided_by_evidence:
            break
        count += 1
    return count


def _verdict(
    value: int,
    *,
    warn_at: int,
    abort_at: int,
    reason_warn: str,
    reason_abort: str,
    warned_at_l2: bool,
) -> ConvergenceVerdict | None:
    """把一个计数值映射到分级；未达任何阈值返回 None。

    「先警告后熔断」实现在这里：达到熔断阈值但没有 L2 记录时，降级为 L2。
    """
    if value >= abort_at and warned_at_l2:
        return ConvergenceVerdict(level=3, reason=reason_abort, should_abort=True)
    if value >= warn_at:
        return ConvergenceVerdict(level=2, reason=reason_warn, should_abort=False)
    if value >= warn_at - 1:
        return ConvergenceVerdict(level=1, reason=reason_warn, should_abort=False)
    return None


def evaluate_convergence(
    steps: Sequence[AgentStep],
    *,
    warned_at_l2: bool,
) -> ConvergenceVerdict:
    """按三判据给出收敛判定。

    Args:
        steps: 本轮的完整动作序列（时间正序，最后一个是最新一步）。
        warned_at_l2: 本轮此前是否已经发出过 L2 提示。L3 熔断的前置条件。
    """
    if len(steps) < MIN_STEPS_FOR_JUDGEMENT:
        return NO_STALL

    repeat = _trailing_repeat_steps(steps)
    repeat_verdict = _verdict(
        repeat,
        warn_at=REPEAT_WARN_STEPS,
        abort_at=REPEAT_ABORT_STEPS,
        reason_warn="连续重复同一动作且结果相同，未产生新进展",
        reason_abort="连续重复同一动作已达熔断阈值",
        warned_at_l2=warned_at_l2,
    )
    if repeat_verdict is not None:
        return repeat_verdict

    stalled = _steps_without_fact_gain(steps)
    stalled_verdict = _verdict(
        stalled,
        warn_at=STALL_WARN_STEPS,
        abort_at=STALL_ABORT_STEPS,
        reason_warn="事实数连续多步无增长，取证未带来新信息",
        reason_abort="事实数长期无增长，判定停滞",
        warned_at_l2=warned_at_l2,
    )
    if stalled_verdict is not None:
        return stalled_verdict

    blind = _steps_without_evidence(steps)
    blind_verdict = _verdict(
        blind,
        warn_at=STALL_WARN_STEPS,
        abort_at=STALL_ABORT_STEPS,
        reason_warn="连续多步决策缺少实测依据",
        reason_abort="长期无实测依据推进，判定停滞",
        warned_at_l2=warned_at_l2,
    )
    if blind_verdict is not None:
        return blind_verdict

    return NO_STALL
