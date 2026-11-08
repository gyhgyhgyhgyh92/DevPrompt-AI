"""F-404 推荐标记：MUST-27 双阈值诚实策略（纯逻辑零 I/O，MUST-06/MUST-08）。

判定五条按优先级顺序执行、命中即止；不标记时必须给具体原因文案，不得静默
（宁可不标记，也不制造虚假确定性）。阈值常量模块级 UPPER_SNAKE（MUST-17）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.decision.port import VariantScore

# MUST-27 阈值：条件①②为置信度门禁（优先于一切分差判定），③④⑤为分差双阈值。
TOP_CONF_MIN: Final[float] = 0.6
ANY_CONF_MIN: Final[float] = 0.4
#: 2026-11-07：打分粒度是 0.25（0~4 五档），0.12 无判别力，改为「一档」。
GAP_SOFT: Final[float] = 0.25
GAP_HARD: Final[float] = 0.5

#: 理由文案的键（2026-11-06 双语）：文案在 common/i18n.py，默认 zh-CN。
_REASON_BASE_KEY: Final[str] = "ranking.conf_base"
_REASON_CLOSE_KEY: Final[str] = "ranking.conf_close"
_REASON_SMALL_GAP_KEY: Final[str] = "ranking.conf_small_gap"


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


def decide_mark(
    entries: list[tuple[VariantScore, float]], locale: Locale = DEFAULT_LOCALE
) -> RecommendationResult:
    """MUST-27 五条优先级判定，命中即止。

    契约：entries 为 [(VariantScore, 该档加权总分)]，总分已由调用方按 F-403
    合成（normalize_fit → match_score → weighted_total）；本函数不计算总分，
    只按总分排序后执行阈值判定。len(entries) < 2 抛 ValueError
    （MUST-28：单套方案跳过打分与推荐判定，由 service 保证不调用）。
    """
    if len(entries) < 2:
        raise ValueError(tr("ranking.need_two", locale, count=len(entries)))

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
            reason=tr(
                "ranking.conf_top",
                locale,
                base=tr(_REASON_BASE_KEY, locale),
                conf=f"{top_score.confidence:.2f}",
                min=TOP_CONF_MIN,
            ),
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
            reason=tr(
                "ranking.conf_any",
                locale,
                base=tr(_REASON_BASE_KEY, locale),
                conf=f"{min_conf:.2f}",
                min=ANY_CONF_MIN,
            ),
        )

    # ③ 分差低于软阈值：三套适配度接近。
    if gap < GAP_SOFT:
        return RecommendationResult(
            variant=top_score.variant,
            gap=gap,
            confidence=top_score.confidence,
            marked=False,
            reason=tr(_REASON_CLOSE_KEY, locale),
        )

    # ④⑤ 双阈值标记：d ≥ 0.5 正向推荐；0.25 ≤ d < 0.5 标记但附「分差较小」。
    reason = tr(_REASON_SMALL_GAP_KEY, locale) if gap < GAP_HARD else ""
    return RecommendationResult(
        variant=top_score.variant,
        gap=gap,
        confidence=top_score.confidence,
        marked=True,
        reason=reason,
    )
