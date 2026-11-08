"""路由打分（G10）：胜率减延迟罚的 bandit，纯函数。

为什么不做复杂算法：模型数量小（个位数）、反馈稀疏；胜率 + 延迟罚已经足够，
且每一项都能解释给用户看。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

#: 没有样本时给中性 0.5，不冒充「表现好」。
_PRIOR_SUCCESS_RATE: Final[float] = 0.5
#: 每毫秒延迟的惩罚系数：10s ≈ 0.5 分，足以让慢模型让位。
_LATENCY_PENALTY_PER_MS: Final[float] = 0.00005


@dataclass(frozen=True, slots=True)
class RoutingStat:
    attempts: int = 0
    successes: int = 0
    total_latency_ms: int = 0


def success_rate(stat: RoutingStat) -> float:
    if stat.attempts <= 0:
        return _PRIOR_SUCCESS_RATE
    return stat.successes / stat.attempts


def average_latency_ms(stat: RoutingStat) -> float:
    if stat.attempts <= 0:
        return 0.0
    return stat.total_latency_ms / stat.attempts


def bandit_score(stat: RoutingStat) -> float:
    """胜率减去延迟罚；值域可能略小于 0，排序用不截断。"""
    return success_rate(stat) - average_latency_ms(stat) * _LATENCY_PENALTY_PER_MS


def should_explore(epsilon: float, rng: random.Random | None = None) -> bool:
    return (rng or random).random() < max(0.0, min(1.0, epsilon))


def pick_model(
    candidates: Sequence[str],
    stats: Mapping[tuple[str, str], tuple[int, int, int]],
    *,
    task_kind: str,
    epsilon: float = 0.1,
    rng: random.Random | None = None,
) -> str | None:
    """在候选里选一个；探索时随机，否则取胜率最高，平手按传入顺序。"""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if should_explore(epsilon, rng):
        return (rng or random).choice(list(candidates))
    best = candidates[0]
    best_score = _score_for(best, stats, task_kind)
    for model in candidates[1:]:
        score = _score_for(model, stats, task_kind)
        if score > best_score:
            best, best_score = model, score
    return best


def _score_for(
    model: str,
    stats: Mapping[tuple[str, str], tuple[int, int, int]],
    task_kind: str,
) -> float:
    raw = stats.get((model, task_kind))
    if raw is None:
        return _PRIOR_SUCCESS_RATE
    attempts, successes, latency = raw
    return bandit_score(RoutingStat(attempts, successes, latency))
