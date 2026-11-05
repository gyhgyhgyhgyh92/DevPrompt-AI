"""六维状态感知（2026-11-05）：外环监督的观测层。

天枢 Sensorium 的轻量移植（`src/agent/sensorium.ts:321`）：纯函数、零 I/O、不调 LLM，
六维全部来自已有信号（`AgentStep` / 成本 / claims / 记忆命中 / 轮次）。

**本阶段只观测**：结果写 `session.data["sensorium"]` 并 emit 事件，
不参与 `convergence.evaluate_convergence` 的判定（shadow 模式）——先收真实数据，
再决定是否升级为第四判据。这样即使六维权重的直觉有偏差，也不会影响既有熔断行为。
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome

#: 动量窗口：与收敛判据的「最近几步」口径保持一致
MOMENTUM_WINDOW: Final = 5
#: 熟悉度饱和点：命中 5 条记忆或走过 5 轮即视为「熟」
FAMILIARITY_SATURATION: Final = 5
#: 六维权重（和为 1）。写成常量便于测试与后续调参。
WEIGHTS: Final[tuple[tuple[str, float], ...]] = (
    ("momentum", 0.20),
    ("pressure", 0.15),
    ("coverage", 0.25),
    ("complexity", 0.10),
    ("familiarity", 0.10),
    ("stability", 0.20),
)


@dataclass(frozen=True, slots=True)
class SensoriumInput:
    """一次观测的输入（全部来自会话内已有字段，无需额外采集）。"""

    steps: Sequence[AgentStep] = ()
    max_steps: int = 24
    cost_tokens: int = 0
    cost_budget: int = 0
    #: claims 覆盖率；None 表示本轮没有任何断言（按 0 计，不再视为「完全覆盖」）
    claim_coverage: float | None = None
    notes_hit: int = 0
    turn_index: int = 0


@dataclass(frozen=True, slots=True)
class SensoriumSnapshot:
    """六维取值 + 加权总分。各维均已归一化到 [0, 1]。"""

    momentum: float
    pressure: float
    coverage: float
    complexity: float
    familiarity: float
    stability: float
    score: float

    def as_payload(self) -> dict[str, float]:
        return {
            "momentum": round(self.momentum, 4),
            "pressure": round(self.pressure, 4),
            "coverage": round(self.coverage, 4),
            "complexity": round(self.complexity, 4),
            "familiarity": round(self.familiarity, 4),
            "stability": round(self.stability, 4),
            "score": round(self.score, 4),
        }


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _momentum(steps: Sequence[AgentStep]) -> float:
    """最近窗口内成功步的占比。无步时给中性 0.5，不冒充「顺利」。"""
    if not steps:
        return 0.5
    window = steps[-MOMENTUM_WINDOW:]
    ok = sum(1 for step in window if step.outcome is StepOutcome.OK)
    return ok / len(window)


def _pressure(step_count: int, max_steps: int, cost_tokens: int, cost_budget: int) -> float:
    """步数压力 0.6 + 成本压力 0.4；未设成本预算时只看步数。"""
    step_ratio = _clamp(step_count / max_steps) if max_steps > 0 else 0.0
    if cost_budget <= 0:
        return step_ratio
    return _clamp(0.6 * step_ratio + 0.4 * _clamp(cost_tokens / cost_budget))


def _coverage(claim_coverage: float | None) -> float:
    """断言覆盖率。无声明记 0：不声明不等于全覆盖（与 claims 对账同口径）。"""
    return 0.0 if claim_coverage is None else _clamp(claim_coverage)


def _complexity(steps: Sequence[AgentStep]) -> float:
    """动作类型分布的归一化 Shannon 熵：动作越杂越高。"""
    if not steps:
        return 0.0
    counts = Counter(step.action for step in steps)
    total = sum(counts.values())
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    ceiling = math.log(len(AgentAction))
    return _clamp(entropy / ceiling) if ceiling > 0 else 0.0


def _familiarity(notes_hit: int, turn_index: int) -> float:
    """记忆命中与轮次深度。冷启动（两者皆 0）给 0.5，避免把「新会话」当成「不熟」。"""
    if notes_hit <= 0 and turn_index <= 0:
        return 0.5
    notes = _clamp(notes_hit / FAMILIARITY_SATURATION)
    depth = _clamp(turn_index / FAMILIARITY_SATURATION)
    return _clamp(0.6 * notes + 0.4 * depth)


def _stability(steps: Sequence[AgentStep]) -> float:
    """稳定性 = 1 − 重复动作占比 − 无实证依据占比。无步时满分。"""
    if not steps:
        return 1.0
    last = steps[-1]
    repeat = 0
    for step in reversed(steps):
        if step.action is not last.action or step.outcome is not last.outcome:
            break
        repeat += 1
    blind = 0
    for step in reversed(steps):
        if step.decided_by_evidence:
            break
        blind += 1
    total = len(steps)
    return _clamp(1.0 - 0.5 * (repeat / total) - 0.5 * (blind / total))


def compute_sensorium(data: SensoriumInput) -> SensoriumSnapshot:
    """计算六维与加权总分。纯函数：同一输入永远得到同一输出。"""
    dims = {
        "momentum": _momentum(data.steps),
        "pressure": _pressure(len(data.steps), data.max_steps, data.cost_tokens, data.cost_budget),
        "coverage": _coverage(data.claim_coverage),
        "complexity": _complexity(data.steps),
        "familiarity": _familiarity(data.notes_hit, data.turn_index),
        "stability": _stability(data.steps),
    }
    score = sum(dims[name] * weight for name, weight in WEIGHTS)
    return SensoriumSnapshot(
        momentum=dims["momentum"],
        pressure=dims["pressure"],
        coverage=dims["coverage"],
        complexity=dims["complexity"],
        familiarity=dims["familiarity"],
        stability=dims["stability"],
        score=_clamp(score),
    )
