"""F-404 推荐标记：MUST-27 双阈值诚实策略（纯逻辑零 I/O，MUST-06/MUST-08）。

判定五条按优先级顺序执行、命中即止；不标记时必须给具体原因文案，不得静默
（宁可不标记，也不制造虚假确定性）。阈值常量模块级 UPPER_SNAKE（MUST-17）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from devprompt_ai.domain.decision.port import VariantScore

# MUST-27 阈值：条件①②为置信度门禁（优先于一切分差判定），③④⑤为分差双阈值。
TOP_CONF_MIN: Final[float] = 0.6
ANY_CONF_MIN: Final[float] = 0.4
GAP_SOFT: Final[float] = 0.12
GAP_HARD: Final[float] = 0.5

REASON_CONF_BASE: Final[str] = "置信度不足，建议人工选择"
REASON_CLOSE: Final[str] = "三套适配度接近，建议人工选择"
REASON_SMALL_GAP: Final[str] = "分差较小"


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    """F-404 判定输出：是否推荐 / 推荐项 / 分差 / 置信度 / 原因。

    variant 恒为最高总分档位（marked=False 时作为人工选择的默认候选展示）；
    marked=True 且 reason 为空表示分差显著的正向推荐，非空表示附「分差较小」。
    """

    variant: str
    gap: float
    confidence: float
    marked: bool
    reason: str


def decide_mark(entries: list[tuple[VariantScore, float]]) -> RecommendationResult:
    """MUST-27 五条优先级判定，命中即止。

    契约：entries 为 [(VariantScore, 该档加权总分)]，总分已由调用方按 F-403
    合成（normalize_fit → match_score → weighted_total）；本函数不计算总分，
    只按总分排序后执行阈值判定。len(entries) < 2 抛 ValueError
    （MUST-28：单套方案跳过打分与推荐判定，由 service 保证不调用）。
    """
    if len(entries) < 2:
        raise ValueError(f"推荐判定需要至少 2 套方案（MUST-28），实际 {len(entries)}")

    ranked = sorted(entries, key=lambda entry: entry[1], reverse=True)
    top_score, top_total = ranked[0]
    second_total = ranked[1][1]
    gap = top_total - second_total

    # ① 最高分档置信度不足——置信度优先于分差，无论 gap 多大。
    if top_score.confidence < TOP_CONF_MIN:
        return RecommendationResult(
            variant=top_score.variant,
            gap=gap,
            confidence=top_score.confidence,
            marked=False,
            reason=(f"{REASON_CONF_BASE}（最高档 {top_score.confidence:.2f} < {TOP_CONF_MIN}）"),
        )

    # ② 任一档（非「三档均」）置信度不足——避免两档低置信时被绕过。
    all_conf = [score.confidence for score, _ in ranked]
    if any(conf < ANY_CONF_MIN for conf in all_conf):
        min_conf = min(all_conf)
        return RecommendationResult(
            variant=top_score.variant,
            gap=gap,
            confidence=top_score.confidence,
            marked=False,
            reason=f"{REASON_CONF_BASE}（最低档 {min_conf:.2f} < {ANY_CONF_MIN}）",
        )

    # ③ 分差低于软阈值：三套适配度接近。
    if gap < GAP_SOFT:
        return RecommendationResult(
            variant=top_score.variant,
            gap=gap,
            confidence=top_score.confidence,
            marked=False,
            reason=REASON_CLOSE,
        )

    # ④⑤ 双阈值标记：d ≥ 0.5 正向推荐；0.12 ≤ d < 0.5 标记但附「分差较小」。
    reason = REASON_SMALL_GAP if gap < GAP_HARD else ""
    return RecommendationResult(
        variant=top_score.variant,
        gap=gap,
        confidence=top_score.confidence,
        marked=True,
        reason=reason,
    )
