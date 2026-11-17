"""相位感知的收敛判定（E5–E8）：七信号 + 相位权重 + 双门槛 + 五道否决。

与 `convergence.py` 的分工：后者是「连续重复/停滞」的三判据兜底，本模块按当前阶段
加权打分，解决「同一分数在探索期与执行期含义完全不同」的误判。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from devprompt_ai.domain.agent.action import AgentStep, StepOutcome

#: 生产性动作：编辑/测试/提交才算推进；只读不算。
PRODUCTIVE_ACTIONS: Final[frozenset[str]] = frozenset({"generate", "deliver"})


class PhaseClass(str, Enum):
    EXPLORE = "explore"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    DELIVER = "deliver"


@dataclass(frozen=True, slots=True)
class PhaseWeights:
    edit_ratio: float
    target_novelty: float
    tool_entropy: float
    error_penalty: float
    token_efficiency: float
    oscillation_penalty: float
    text_repetition_penalty: float


#: 五套权重（每行和为 1）：探索看新颖度、执行看改动、验证看错误率、交付看效率。
PHASE_WEIGHTS: Final[dict[PhaseClass, PhaseWeights]] = {
    PhaseClass.EXPLORE: PhaseWeights(0.05, 0.25, 0.20, 0.12, 0.13, 0.10, 0.15),
    PhaseClass.PLAN: PhaseWeights(0.15, 0.18, 0.15, 0.13, 0.18, 0.10, 0.11),
    PhaseClass.EXECUTE: PhaseWeights(0.40, 0.08, 0.08, 0.18, 0.08, 0.06, 0.12),
    PhaseClass.VERIFY: PhaseWeights(0.05, 0.08, 0.08, 0.35, 0.18, 0.12, 0.14),
    PhaseClass.DELIVER: PhaseWeights(0.15, 0.08, 0.08, 0.25, 0.24, 0.08, 0.12),
}


@dataclass(frozen=True, slots=True)
class WindowTier:
    max_turns: int
    n_low: int
    n_mid: int
    n_high: int
    signal_window: int


_TIER_200K: Final[WindowTier] = WindowTier(30, 8, 14, 20, 6)
_TIER_1M: Final[WindowTier] = WindowTier(50, 25, 34, 42, 10)


def select_tier(context_window: int) -> WindowTier:
    """按窗口线性插值；≤200K 用低档，≥1M 用高档。"""
    if context_window <= 200_000:
        return _TIER_200K
    if context_window >= 1_000_000:
        return _TIER_1M
    ratio = (context_window - 200_000) / 800_000
    return WindowTier(
        max_turns=round(_TIER_200K.max_turns + (_TIER_1M.max_turns - _TIER_200K.max_turns) * ratio),
        n_low=round(_TIER_200K.n_low + (_TIER_1M.n_low - _TIER_200K.n_low) * ratio),
        n_mid=round(_TIER_200K.n_mid + (_TIER_1M.n_mid - _TIER_200K.n_mid) * ratio),
        n_high=round(_TIER_200K.n_high + (_TIER_1M.n_high - _TIER_200K.n_high) * ratio),
        signal_window=round(
            _TIER_200K.signal_window + (_TIER_1M.signal_window - _TIER_200K.signal_window) * ratio
        ),
    )


@dataclass(frozen=True, slots=True)
class Verdict:
    level: int
    score: float
    reason: str = ""

    @property
    def should_abort(self) -> bool:
        return self.level >= 3


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _edit_ratio(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    return sum(1 for step in recent if step.action.value in PRODUCTIVE_ACTIONS) / len(recent)


def _target_novelty(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    unique = len({(step.action, step.note) for step in recent})
    return unique / len(recent)


def _tool_entropy(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    counts: dict[str, int] = {}
    for step in recent:
        counts[step.action.value] = counts.get(step.action.value, 0) + 1
    return min(1.0, len(counts) / max(1, len(recent)))


def _error_penalty(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    failed = sum(1 for step in recent if step.outcome is StepOutcome.FAILED)
    return _clamp(1.0 - failed / len(recent))


def _token_efficiency(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    avg_ms = sum(step.duration_ms for step in recent) / len(recent)
    return _clamp(1.0 - avg_ms / 60_000.0)


def _oscillation_penalty(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if len(recent) < 3:
        return 1.0
    flips = sum(
        1 for prev, cur in zip(recent, recent[1:], strict=False) if prev.action is not cur.action
    )
    return _clamp(1.0 - flips / max(1, len(recent) - 1))


def _text_repetition_penalty(steps: list[AgentStep], window: int) -> float:
    recent = steps[-window:]
    if not recent:
        return 1.0
    notes = [step.note for step in recent if step.note]
    if not notes:
        return 1.0
    return len(set(notes)) / len(notes)


def score_signals(steps: list[AgentStep], phase: PhaseClass, *, window: int) -> float:
    weights = PHASE_WEIGHTS[phase]
    score = (
        weights.edit_ratio * _edit_ratio(steps, window)
        + weights.target_novelty * _target_novelty(steps, window)
        + weights.tool_entropy * _tool_entropy(steps, window)
        + weights.error_penalty * _error_penalty(steps, window)
        + weights.token_efficiency * _token_efficiency(steps, window)
        + weights.oscillation_penalty * _oscillation_penalty(steps, window)
        + weights.text_repetition_penalty * _text_repetition_penalty(steps, window)
    )
    return _clamp(score)


def evaluate_phase(
    steps: list[AgentStep],
    *,
    phase: PhaseClass,
    context_window: int,
    turn: int | None = None,
    no_tool_count: int = 0,
    reasoning_active: bool = False,
    todo_completed: bool = False,
    awaiting_verification: bool = False,
    repeated_verification: bool = False,
) -> Verdict:
    """按「分数 × 轮次」双门槛给等级，再叠加反向证据与五道否决。"""
    tier = select_tier(context_window)
    score = score_signals(steps, phase, window=tier.signal_window)
    current_turn = len(steps) if turn is None else turn

    if no_tool_count >= 5:
        level = 2 if reasoning_active else 3
        return Verdict(level, score, "no-tool stagnation")

    if current_turn >= tier.n_high and score <= 0.20:
        level = 3
    elif current_turn >= tier.n_mid and score <= 0.40:
        level = 2
    elif current_turn >= tier.n_low and score <= 0.60:
        level = 1
    else:
        level = 0

    reason = "score-threshold" if level > 0 else ""

    # E8 反向证据：在输出新鲜实质文本 → 熔断降两级，改为提醒。
    if reasoning_active and level >= 3:
        level, reason = 2, "reasoning-active"

    # E7 否决：完成的 todo / 正在等验证 → 最多 L1。
    if (todo_completed or awaiting_verification) and level > 1:
        level, reason = 1, "progress-beacon"

    # 重复验证只上探到 L2，不独立触发熔断。
    if repeated_verification and level < 2:
        level, reason = 2, "repeated-verification"

    if current_turn < tier.n_low and no_tool_count < 2:
        level, reason = 0, ""
    return Verdict(level, score, reason)
