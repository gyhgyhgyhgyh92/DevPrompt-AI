"""压缩编排测试：决策树 + 缓存顾问 + 经济性复核。"""

from __future__ import annotations

from devprompt_ai.domain.context.compact_economics import Billing, reclaim_floor
from devprompt_ai.domain.context.compact_policy import CacheKind, CompactAction
from devprompt_ai.domain.context.compactor import confirm_reclaim, plan_compaction


def test_below_watch_does_nothing() -> None:
    plan = plan_compaction(
        estimated_tokens=100_000,
        window=1_000_000,
        cache_kind=CacheKind.AUTOMATIC,
    )

    assert plan.should_compact is False
    assert plan.reason == "below-watch"


def test_high_ratio_plans_micro_with_budget() -> None:
    # 100K 窗口没有 1M 阶梯与精度带，ratio=0.6 落在 NONE 档的 compact(0.70) 之下
    plan = plan_compaction(
        estimated_tokens=60_000,
        window=100_000,
        cache_kind=CacheKind.NONE,
    )

    assert plan.action is CompactAction.MICRO
    assert plan.budget_ratio == 0.70
    assert plan.force is False


def test_ceiling_forces_checkpoint() -> None:
    plan = plan_compaction(
        estimated_tokens=980_000,
        window=1_000_000,
        cache_kind=CacheKind.EXPLICIT,
    )

    assert plan.action is CompactAction.CHECKPOINT
    assert plan.force is True
    assert plan.budget_ratio == 0.45


def test_hot_cache_delays_compaction() -> None:
    plan = plan_compaction(
        estimated_tokens=60_000,
        window=100_000,
        cache_kind=CacheKind.AUTOMATIC,
        recent_hit_rate=0.95,
        pressure=0.1,
    )

    assert plan.should_compact is False
    assert plan.reason == "cache-protection"


def test_reactive_tier_never_delays() -> None:
    plan = plan_compaction(
        estimated_tokens=90_000,
        window=100_000,
        cache_kind=CacheKind.NONE,
        recent_hit_rate=1.0,
        pressure=0.0,
    )

    assert plan.should_compact is True, "tier≥3 时缓存收益不能压过溢出风险"


def test_confirm_reclaim_rejects_pointless_rewrite() -> None:
    floor = reclaim_floor(
        billing=Billing.PER_TOKEN, cache_kind=CacheKind.EXPLICIT, window=1_000_000
    )

    assert confirm_reclaim(before_tokens=1000, after_tokens=950, floor=floor).worthwhile is False
    assert (
        confirm_reclaim(before_tokens=100_000, after_tokens=40_000, floor=floor).worthwhile is True
    )
    assert (
        confirm_reclaim(before_tokens=1000, after_tokens=950, floor=floor, force=True).worthwhile
        is True
    )
