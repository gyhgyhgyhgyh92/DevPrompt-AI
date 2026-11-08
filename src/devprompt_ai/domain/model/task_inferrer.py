"""任务类型推断与复杂度分档（G4–G5）。

只做粗粒度三档：探查/生成/审查。误判的代价可控——路由到更强模型只是多花钱。

状态：路由已按 purpose 直接分档，业主裁定（2026-11-08）不需要消费方，维持单测覆盖不接线。
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from devprompt_ai.domain.model.registry import ModelTier


class TaskKind(str, Enum):
    PROBE = "probe"
    GENERATE = "generate"
    RANK = "rank"
    REVIEW = "review"
    INVESTIGATE = "investigate"


_KEYWORDS: Final[tuple[tuple[TaskKind, tuple[str, ...]], ...]] = (
    (TaskKind.REVIEW, ("审查", "review", "检查", "风险", "安全")),
    (TaskKind.INVESTIGATE, ("排查", "为什么", "定位", "debug", "诊断", "原因")),
    (TaskKind.RANK, ("排序", "推荐", "哪个更好", "对比")),
    (TaskKind.GENERATE, ("生成", "写", "改", "加", "实现", "重构", "导出")),
    (TaskKind.PROBE, ("判断", "是否", "有没有", "确认")),
)

#: 复杂度权重：路径、代码块、长句都意味着更强模型。
_HIGH_COMPLEXITY: Final[float] = 0.6
_MEDIUM_COMPLEXITY: Final[float] = 0.3


def infer_task(sentence: str) -> TaskKind:
    lowered = sentence.lower()
    for kind, words in _KEYWORDS:
        if any(word in lowered for word in words):
            return kind
    return TaskKind.PROBE


def complexity_score(sentence: str) -> float:
    """0~1 的粗分：长度 + 路径数 + 多句。"""
    text = sentence.strip()
    if not text:
        return 0.0
    length = min(1.0, len(text) / 200.0)
    paths = min(1.0, text.count("/") + text.count("\\")) / 3.0
    clauses = min(1.0, text.count("，") + text.count(",")) / 3.0
    return min(1.0, 0.5 * length + 0.3 * paths + 0.2 * clauses)


def tier_for_complexity(score: float) -> ModelTier:
    if score >= _HIGH_COMPLEXITY:
        return ModelTier.STRONG
    if score >= _MEDIUM_COMPLEXITY:
        return ModelTier.STANDARD
    return ModelTier.CHEAP


def tier_for_task(kind: TaskKind) -> ModelTier:
    """轻活给便宜模型：探查/排序/审查不需要最强模型。"""
    if kind is TaskKind.GENERATE:
        return ModelTier.STRONG
    if kind is TaskKind.INVESTIGATE:
        return ModelTier.STANDARD
    return ModelTier.CHEAP
