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
from typing import Final, Literal

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
    #: 本轮上下文估算占用与窗口（E3/E4 绝对压力）；窗口 0 表示未设（不参与判定）
    context_tokens: int = 0
    context_window: int = 0
    #: claims 覆盖率；None 表示本轮没有任何断言（按 0 计，不再视为「完全覆盖」）
    claim_coverage: float | None = None
    notes_hit: int = 0
    turn_index: int = 0


@dataclass(frozen=True, slots=True)
class SensoriumQuality:
    """各维数据质量（移植天枢 sensorium.ts:52-61）。

    回退值本身无法区分「实测良好」与「无数据」：momentum 空窗口回退 0.5、
    coverage 无断言回退 0.0。消费方必须看本标记，不得把回退值当实测信号——
    这正是 probe ``no_data`` 被误判为「信息足够」的同类问题。
    """

    momentum: Literal["measured", "no-data"]
    coverage: Literal["measured", "no-data"]
    stability: Literal["measured", "partial"]


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
    quality: SensoriumQuality

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


def _pressure(
    step_count: int,
    max_steps: int,
    cost_tokens: int,
    cost_budget: int,
    context_tokens: int = 0,
    context_window: int = 0,
) -> float:
    """步数压力 0.6 + 成本压力 0.4，再与上下文**绝对占用**取 max（E3/E4）。

    只看相对比例会漏掉「小窗口、步数还少」的场景：窗口小、绝对占用已高时，
    压力必须同样高。未设窗口时不看绝对占用（不猜窗口大小，记 no-data 语义）。
    """
    step_ratio = _clamp(step_count / max_steps) if max_steps > 0 else 0.0
    if cost_budget <= 0:
        relative = step_ratio
    else:
        relative = _clamp(0.6 * step_ratio + 0.4 * _clamp(cost_tokens / cost_budget))
    absolute = _clamp(context_tokens / context_window) if context_window > 0 else 0.0
    return max(relative, absolute)


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


def _quality(data: SensoriumInput) -> SensoriumQuality:
    """标注哪些维度的值是实测、哪些是回退。"""
    return SensoriumQuality(
        momentum="measured" if data.steps else "no-data",
        coverage="measured" if data.claim_coverage is not None else "no-data",
        stability="measured" if data.steps else "partial",
    )


def compute_sensorium(data: SensoriumInput) -> SensoriumSnapshot:
    """计算六维与加权总分。纯函数：同一输入永远得到同一输出。"""
    dims = {
        "momentum": _momentum(data.steps),
        "pressure": _pressure(
            len(data.steps),
            data.max_steps,
            data.cost_tokens,
            data.cost_budget,
            context_tokens=data.context_tokens,
            context_window=data.context_window,
        ),
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
        quality=_quality(data),
    )


# ---- 策略映射（E4）：连续函数，不用阈值悬崖 ----------------


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    reasoning_effort: Literal["low", "medium", "high"]
    exploration_breadth: float
    commit_threshold: float
    theta_cycle_interval: int


def derive_strategy(snapshot: SensoriumSnapshot) -> StrategyProfile:
    """把六维映射为运行时策略；no-data 的 momentum 不当成「卡住」。"""
    measured = snapshot.quality.momentum == "measured"
    if snapshot.complexity > 0.7:
        effort: Literal["low", "medium", "high"] = "high"
    elif measured and snapshot.momentum > 0.8:
        effort = "low"
    else:
        effort = "medium"

    breadth_base = 0.3 + snapshot.complexity * 0.3
    stability_penalty = (0.3 - snapshot.stability) * 1.5 if snapshot.stability < 0.3 else 0.0
    breadth = _clamp(breadth_base + stability_penalty)

    pressure_boost = (snapshot.pressure - 0.7) * 0.5 if snapshot.pressure > 0.7 else 0.0
    momentum_drag = (
        (0.3 - snapshot.momentum) * (0.25 / 0.3) if measured and snapshot.momentum < 0.3 else 0.0
    )
    commit = _clamp(0.5 + pressure_boost + momentum_drag)

    return StrategyProfile(
        reasoning_effort=effort,
        exploration_breadth=breadth,
        commit_threshold=commit,
        theta_cycle_interval=3 if snapshot.complexity > 0.5 else 7,
    )


# ---- 注意力质量（B16）：低于 0.3 时不等 token 满就触发折叠 ----------------


@dataclass(frozen=True, slots=True)
class AttentionMetrics:
    tool_density: float = 0.0
    unique_tool_ratio: float = 1.0
    avg_tool_result_chars: float = 0.0
    user_message_ratio: float = 1.0
    tool_storm: Literal["none", "warn", "storm"] = "none"


def compute_attention_quality(metrics: AttentionMetrics) -> float:
    """五因子加权；值越低说明上下文里噪音越多。"""
    density = 1.0 - _clamp(metrics.tool_density)
    diversity = _clamp(metrics.unique_tool_ratio)
    size = 1.0 - _clamp(metrics.avg_tool_result_chars / 10_000.0)
    user = _clamp(metrics.user_message_ratio * 3.0)
    storm = 0.0 if metrics.tool_storm == "storm" else 0.5 if metrics.tool_storm == "warn" else 1.0
    return _clamp(0.30 * density + 0.25 * diversity + 0.15 * size + 0.20 * user + 0.10 * storm)
