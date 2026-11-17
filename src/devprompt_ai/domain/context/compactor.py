"""压缩编排（B7–B9 的粘合层）：把「决策树 + 缓存顾问 + 经济性」串成一次判定。

拆开三件事的理由：决策树只看占用率，顾问只看缓存收益，经济性只看回收量；
任何一步都不该知道另外两步的存在，编排放在这里，便于单独替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from devprompt_ai.domain.context.advisor import should_delay
from devprompt_ai.domain.context.compact_economics import (
    Billing,
    ReclaimFloor,
    ReclaimVerdict,
    judge_reclaim,
)
from devprompt_ai.domain.context.compact_policy import (
    CacheKind,
    CompactAction,
    CompactDecision,
    decide_compact_action,
)

#: 各动作执行后建议保留的上下文比例（越小压得越狠）。
_BUDGET_RATIO: Final[dict[CompactAction, float]] = {
    CompactAction.NONE: 1.0,
    CompactAction.STALE: 0.80,
    CompactAction.MICRO: 0.70,
    CompactAction.COLLAPSE: 0.65,
    CompactAction.PRUNE: 0.60,
    CompactAction.PARTIAL_LLM: 0.55,
    CompactAction.FULL_LLM: 0.50,
    CompactAction.CHECKPOINT: 0.45,
}


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    action: CompactAction
    tier: int = 0
    force: bool = False
    reason: str = ""
    budget_ratio: float = 1.0

    @property
    def should_compact(self) -> bool:
        return self.action is not CompactAction.NONE


def plan_compaction(
    *,
    estimated_tokens: int,
    window: int,
    cache_kind: CacheKind,
    per_token_billing: bool = False,
    recent_hit_rate: float = 0.0,
    pressure: float = 0.0,
) -> CompactionPlan:
    """返回一次压缩计划；`should_compact=False` 表示本轮不动上下文。"""
    decision: CompactDecision = decide_compact_action(
        estimated_tokens / window if window > 0 else 1.0,
        window=window,
        cache_kind=cache_kind,
        per_token_billing=per_token_billing,
    )
    if not decision.should_compact:
        return CompactionPlan(CompactAction.NONE, reason=decision.reason)
    if should_delay(recent_hit_rate=recent_hit_rate, pressure=pressure, tier=decision.tier):
        return CompactionPlan(CompactAction.NONE, reason="cache-protection")
    return CompactionPlan(
        action=decision.action,
        tier=decision.tier,
        force=decision.force,
        reason=decision.reason,
        budget_ratio=_BUDGET_RATIO[decision.action],
    )


def confirm_reclaim(
    *,
    before_tokens: int,
    after_tokens: int,
    floor: ReclaimFloor,
    force: bool = False,
    billing: Billing = Billing.SUBSCRIPTION,
) -> ReclaimVerdict:
    """执行后复核：回收量不够本则回滚本次压缩（force 不受限）。"""
    del billing  # 计费类型只影响 floor 的计算，复核时不再重复判断
    return judge_reclaim(
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        floor=floor,
        force=force,
    )
