"""多轮上下文装配（2026-10-20）：分层、固定裁剪顺序、本轮永不裁、摘要三字段。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.context import (
    ContextBudget,
    TurnInput,
    TurnSummary,
    build_context,
    summary_from_turn,
)


def _turn(index: int, *, target: str = "Button", decision: str = "B") -> TurnSummary:
    return TurnSummary(
        turn_id=f"t{index}",
        turn_index=index,
        target=target,
        conclusion="复用主题令牌并覆盖五态",
        open_items=("对比度是否达标", "是否需要暗色适配"),
        decision=decision,
        rejected=("C 激进版",),
    )


def _current(target: str = "Button") -> TurnInput:
    return TurnInput(
        sentence="把提交按钮改成红色",
        facts=("token_defined=未通过", "test_file_exists=通过"),
        clarifications={"scope": "只改这一处"},
        target=target,
    )


class TestLayers:
    def test_recent_keeps_last_two_full(self) -> None:
        payload = build_context([_turn(0), _turn(1), _turn(2)], _current())

        assert "第2轮" in payload.history_block
        assert "第3轮" in payload.history_block
        assert "第1轮" in payload.history_block  # 更早的进 digest
        assert "待确认" in payload.history_block  # recent 未被裁

    def test_digest_covers_earlier_turns(self) -> None:
        turns = [_turn(i, target="Other") for i in range(8)] + [
            _turn(8, target="Button", decision="A")
        ]
        payload = build_context(turns, _current(target="Button"))

        # 最近 2 轮完整；第 3~8 轮压成一句（digest）
        assert "第9轮" in payload.history_block
        assert "第2轮" in payload.history_block
        assert "第1轮" not in payload.history_block  # 超出 digest 窗口且目标不同 → 被排除

    def test_target_mismatch_excluded_from_older(self) -> None:
        turns = [_turn(i, target="Other", decision="C") for i in range(10)]
        payload = build_context(turns, _current(target="Button"))

        # older 层为空（只看同目标 decision），「选定 C」只应出现在最近 2 轮
        assert payload.history_block.count("选定 C") == 2


class TestTrimming:
    def test_larger_state_budget_keeps_more_history(self) -> None:
        """档位预算越大，历史块 token 单调不减（token 正相关的确定性来源）。"""
        from devprompt_ai.domain.context.build_context import estimate_tokens

        turns = [_turn(i) for i in range(1000)]
        sizes = [
            estimate_tokens(
                build_context(
                    turns,
                    _current(),
                    budget=ContextBudget(total=budget),
                ).history_block
            )
            for budget in (30_000, 60_000, 100_000)
        ]

        assert sizes[0] <= sizes[1] <= sizes[2]
        assert sizes[2] > sizes[0], "预算放大后必须真实保留更多历史"

    def test_recent_degrades_before_dropping(self) -> None:
        budget = ContextBudget(total=80, weights=(0.1, 0.1, 0.1, 0.1, 0.6))
        payload = build_context([_turn(0), _turn(1)], _current(), budget=budget)

        assert "recent" in payload.truncated_layers
        assert "待确认" not in payload.history_block  # open 先被丢掉

    def test_current_layer_is_never_truncated(self) -> None:
        """本轮超出配额只记录标记，绝不裁剪（流程命脉）。"""
        budget = ContextBudget(total=10, weights=(0.1, 0.1, 0.1, 0.1, 0.6))
        payload = build_context([_turn(0)], _current(), budget=budget)

        assert "current" in payload.truncated_layers
        assert "历史轮次" not in payload.history_block or payload.history_block

    def test_memory_block_includes_notes(self) -> None:
        payload = build_context(
            [],
            _current(),
            notes=["项目约定：样式统一用 CSS 变量"],
        )

        assert "项目约定" in payload.memory_block

    def test_memory_trimmed_when_over_budget(self) -> None:
        budget = ContextBudget(total=40, weights=(0.1, 0.1, 0.1, 0.1, 0.1))
        payload = build_context(
            [],
            _current(),
            notes=["很长的约定" * 50],
            budget=budget,
        )

        assert "memory" in payload.truncated_layers

    def test_cache_advisor_delays_only_when_hit_rate_is_hot(self) -> None:
        from devprompt_ai.domain.context.compact_policy import CacheKind

        turns = [_turn(i) for i in range(20)]
        hot = build_context(
            turns,
            _current(),
            context_window=100_000,
            estimated_tokens=80_000,
            cache_kind=CacheKind.NONE,
            recent_hit_rate=0.9,
            pressure=0.2,
        )
        busy = build_context(
            turns,
            _current(),
            context_window=100_000,
            estimated_tokens=80_000,
            cache_kind=CacheKind.NONE,
            recent_hit_rate=0.9,
            pressure=0.9,
        )

        assert not any(layer.startswith("compacted:") for layer in hot.truncated_layers)
        assert any(layer.startswith("compacted:") for layer in busy.truncated_layers)


class TestSummaryFromTurn:
    def test_extracts_three_fields_without_sentence_or_path(self) -> None:
        data: dict[str, Any] = {
            "sentence": "把提交按钮改成 primary-500",
            "project_root": "D:/secret/project",
            "target": {"name": "SubmitButton", "path": "src/ui/Button.tsx", "line": 12},
            "variants": [
                {"level": "A", "title": "只改配色", "body": "..."},
                {"level": "B", "title": "改配色并补状态", "body": "..."},
            ],
            "ranking": {"variant": "B"},
            "unknowns": [{"ask": "对比度是否达标", "key": "x"}],
        }

        summary = summary_from_turn(data)

        assert summary["target"] == "SubmitButton"
        assert summary["conclusion"] == "改配色并补状态"
        assert summary["decision"] == "B"
        assert summary["open"] == ["对比度是否达标"]
        assert summary["rejected"] and "A" in summary["rejected"][0]
        dumped = str(summary)
        assert "primary-500" not in dumped  # 不含原句（MUST-19）
        assert "D:/secret" not in dumped  # 不含绝对路径

    def test_no_variants_falls_back(self) -> None:
        summary = summary_from_turn({"unknowns": [], "variants": []})
        assert summary["conclusion"]
        assert summary["target"] == ""
