"""压缩核心测试：决策树、经济性、顾问、四种手段与摘要兜底。"""

from __future__ import annotations

from devprompt_ai.domain.context.advisor import should_delay
from devprompt_ai.domain.context.collapse import collapse_tool_output
from devprompt_ai.domain.context.compact_economics import (
    Billing,
    judge_reclaim,
    reclaim_floor,
)
from devprompt_ai.domain.context.compact_policy import (
    CacheKind,
    CompactAction,
    decide_compact_action,
)
from devprompt_ai.domain.context.micro import is_microcompacted, micro_compact
from devprompt_ai.domain.context.prune import is_pruned, prune_content
from devprompt_ai.domain.context.stale import is_stale
from devprompt_ai.domain.context.summary import (
    HANDOFF_SECTIONS,
    deterministic_handoff,
    summary_covers_state,
)


def test_policy_below_watch_does_nothing() -> None:
    decision = decide_compact_action(0.3, window=200_000, cache_kind=CacheKind.AUTOMATIC)

    assert decision.action is CompactAction.NONE
    assert decision.should_compact is False


def test_policy_tier_depends_on_cache_kind() -> None:
    # 100K 窗口没有精度天花板，避免干扰档位断言
    ratio = 0.55

    no_cache = decide_compact_action(ratio, window=100_000, cache_kind=CacheKind.NONE)
    explicit = decide_compact_action(ratio, window=100_000, cache_kind=CacheKind.EXPLICIT)

    assert no_cache.action is CompactAction.MICRO and no_cache.tier == 1
    assert explicit.action is CompactAction.NONE, "精确缓存下 0.55 还没到 watch(0.72)"


def test_policy_uses_full_action_ladder() -> None:
    # 100K 窗口无精度带/1M 阶梯；三档缓存各自覆盖 COLLAPSE/PRUNE
    cases = [
        (CacheKind.NONE, 0.75, 0.90),
        (CacheKind.AUTOMATIC, 0.80, 0.90),
        (CacheKind.EXPLICIT, 0.88, 0.93),
    ]
    micro = decide_compact_action(0.55, window=100_000, cache_kind=CacheKind.NONE)
    assert micro.action is CompactAction.MICRO and micro.tier == 1

    for cache_kind, collapse_ratio, prune_ratio in cases:
        collapse = decide_compact_action(collapse_ratio, window=100_000, cache_kind=cache_kind)
        prune = decide_compact_action(prune_ratio, window=100_000, cache_kind=cache_kind)
        assert collapse.action is CompactAction.COLLAPSE and collapse.tier == 2
        assert prune.action is CompactAction.PRUNE and prune.tier == 3


def test_policy_ceiling_forces_checkpoint_on_large_window() -> None:
    decision = decide_compact_action(0.96, window=1_000_000, cache_kind=CacheKind.EXPLICIT)

    assert decision.action is CompactAction.CHECKPOINT
    assert decision.force is True
    assert decision.tier == 4


def test_policy_1m_ladder() -> None:
    partial = decide_compact_action(0.62, window=1_000_000, cache_kind=CacheKind.NONE)
    full = decide_compact_action(0.80, window=1_000_000, cache_kind=CacheKind.NONE)

    assert partial.action is CompactAction.PARTIAL_LLM
    assert full.action is CompactAction.FULL_LLM


def test_policy_precision_band_triggers_stale() -> None:
    # 500K 窗口的精度天花板是 0.70：超过即触发 stale（早于缓存档位的 watch）
    decision = decide_compact_action(0.72, window=500_000, cache_kind=CacheKind.EXPLICIT)

    assert decision.action is CompactAction.STALE
    assert decision.reason == "precision-band"


def test_economics_floors_by_profile() -> None:
    large = reclaim_floor(
        billing=Billing.PER_TOKEN, cache_kind=CacheKind.EXPLICIT, window=1_000_000
    )
    small = reclaim_floor(billing=Billing.PER_TOKEN, cache_kind=CacheKind.EXPLICIT, window=200_000)
    cheap = reclaim_floor(billing=Billing.SUBSCRIPTION, cache_kind=CacheKind.NONE, window=200_000)

    assert large.min_tokens == 50_000
    assert small.min_tokens == 8_192
    assert cheap.min_tokens == 4_096


def test_economics_rejects_pointless_rewrite() -> None:
    floor = reclaim_floor(
        billing=Billing.PER_TOKEN, cache_kind=CacheKind.EXPLICIT, window=1_000_000
    )

    assert judge_reclaim(before_tokens=1000, after_tokens=1000, floor=floor).worthwhile is False
    assert judge_reclaim(before_tokens=1000, after_tokens=900, floor=floor).reason == (
        "below-token-floor"
    )
    assert judge_reclaim(before_tokens=1000, after_tokens=900, floor=floor, force=True).worthwhile


def test_advisor_delays_only_when_cache_is_hot_and_pressure_low() -> None:
    assert should_delay(recent_hit_rate=0.9, pressure=0.2, tier=1) is True
    assert should_delay(recent_hit_rate=0.9, pressure=0.8, tier=1) is False
    assert should_delay(recent_hit_rate=0.9, pressure=0.1, tier=3) is False


def test_micro_marks_truncation() -> None:
    text = "x" * 2000
    compacted = micro_compact(text, preview_chars=100)

    assert is_microcompacted(compacted)
    assert "original_chars=2000" in compacted
    assert micro_compact("short") == "short"


def test_collapse_grep_keeps_counts_not_body() -> None:
    text = "\n".join(f"src/f{i % 3}.py:{i}:match" for i in range(10))

    collapsed = collapse_tool_output("grep", text)

    assert "10 matches" in collapsed
    assert "3 files" in collapsed
    assert "match\n" not in collapsed


def test_collapse_read_file_lists_symbols() -> None:
    text = "def alpha():\n    pass\nclass Beta:\n    pass\n" + "x\n" * 100

    collapsed = collapse_tool_output("read_file", text)

    assert "104 lines" in collapsed
    assert "alpha" in collapsed and "Beta" in collapsed


def test_collapse_bash_keeps_errors_and_tail() -> None:
    text = "\n".join(["ok"] * 50 + ["Error: boom", "done"])

    collapsed = collapse_tool_output("bash", text)

    assert "Error: boom" in collapsed
    assert "done" in collapsed


def test_collapse_unknown_tool_falls_back_to_micro() -> None:
    collapsed = collapse_tool_output("unknown", "y" * 5000, fallback_chars=50)

    assert is_microcompacted(collapsed)


def test_prune_replaces_content_only() -> None:
    pruned = prune_content("z" * 500, reason="duplicate", artifact_id="abc")

    assert is_pruned(pruned)
    assert "500" in pruned and "abc" in pruned


def test_stale_guards() -> None:
    assert is_stale(content_chars=1000, lag_steps=2, suffix_tokens=100) is False
    assert is_stale(content_chars=100, lag_steps=5, suffix_tokens=100) is False
    assert is_stale(content_chars=1000, lag_steps=5, suffix_tokens=9000) is False
    assert is_stale(content_chars=1000, lag_steps=5, suffix_tokens=100, superseded=True)
    assert not is_stale(content_chars=1000, lag_steps=5, suffix_tokens=100, referenced=True)


def test_handoff_has_nine_sections_and_can_be_checked() -> None:
    text = deterministic_handoff(
        objective="把导出按钮加上",
        decisions=["复用现有 Button"],
        files=["src/ui/Button.tsx"],
        errors=["测试未跑"],
        current="正在补测试",
        done=["定位目标"],
        todo=["补测试"],
        recent_tools=["grep Button"],
        next_step="跑测试",
    )

    for section in HANDOFF_SECTIONS:
        assert section in text
    assert summary_covers_state(text, ["导出按钮", "src/ui/Button.tsx"])
    assert summary_covers_state(text, ["不存在的项"]) is False
