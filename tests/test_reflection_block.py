"""Reflection 经验区块纯函数测试（2026-11-22）。

覆盖三层：合并（顺序/去重/截断）、预算裁剪（截断标记）、渲染（双语与空输入）。
"""

from __future__ import annotations

from devprompt_ai.domain.reflection.block import (
    MAX_HIT_CHARS,
    fit_block,
    merge_hits,
    render_block,
)
from devprompt_ai.domain.reflection.port import ReflectionHit, ReflectionScope


def _hit(scope: ReflectionScope, text: str, score: float = 0.0) -> ReflectionHit:
    return ReflectionHit(scope=scope, text=text, score=score)


class TestMergeHits:
    def test_orders_by_score_and_project_wins_ties(self) -> None:
        project = [_hit(ReflectionScope.PROJECT, "项目经验 A", 0.5)]
        global_ = [_hit(ReflectionScope.GLOBAL, "全局经验 B", 0.5)]

        merged = merge_hits(project, global_, top_k=5)

        assert [item.text for item in merged] == ["项目经验 A", "全局经验 B"]
        assert [item.scope for item in merged] == [
            ReflectionScope.PROJECT,
            ReflectionScope.GLOBAL,
        ]

    def test_higher_score_comes_first_across_buckets(self) -> None:
        project = [_hit(ReflectionScope.PROJECT, "低分", 0.1)]
        global_ = [_hit(ReflectionScope.GLOBAL, "高分", 0.9)]

        merged = merge_hits(project, global_, top_k=5)

        assert [item.text for item in merged] == ["高分", "低分"]

    def test_dedupes_ignoring_case_and_extra_spaces(self) -> None:
        project = [_hit(ReflectionScope.PROJECT, "Use pnpm", 0.9)]
        global_ = [_hit(ReflectionScope.GLOBAL, "  use   PNPM ", 0.4)]

        merged = merge_hits(project, global_, top_k=5)

        assert len(merged) == 1
        assert merged[0].scope is ReflectionScope.PROJECT
        assert merged[0].score == 0.9

    def test_caps_to_top_k(self) -> None:
        project = [_hit(ReflectionScope.PROJECT, f"p{i}", 1.0 - i * 0.1) for i in range(4)]

        merged = merge_hits(project, [], top_k=2)

        assert len(merged) == 2

    def test_top_k_zero_means_unlimited(self) -> None:
        project = [_hit(ReflectionScope.PROJECT, f"p{i}", 1.0 - i * 0.1) for i in range(4)]

        assert len(merge_hits(project, [], top_k=0)) == 4

    def test_skips_blank_text(self) -> None:
        merged = merge_hits([_hit(ReflectionScope.PROJECT, "   ", 1.0)], [], top_k=3)

        assert merged == []

    def test_truncates_single_hit(self) -> None:
        merged = merge_hits([_hit(ReflectionScope.PROJECT, "x" * (MAX_HIT_CHARS + 50), 1.0)], [], 3)

        assert len(merged) == 1
        assert len(merged[0].text) == MAX_HIT_CHARS


class TestFitBlock:
    def test_keeps_all_within_budget(self) -> None:
        hits = [_hit(ReflectionScope.PROJECT, "a" * 10), _hit(ReflectionScope.GLOBAL, "b" * 10)]

        kept, truncated = fit_block(hits, max_chars=100)

        assert len(kept) == 2
        assert truncated is False

    def test_truncates_and_flags(self) -> None:
        hits = [_hit(ReflectionScope.PROJECT, "a" * 10), _hit(ReflectionScope.GLOBAL, "b" * 10)]

        kept, truncated = fit_block(hits, max_chars=15)

        assert [len(item.text) for item in kept] == [10]
        assert truncated is True

    def test_zero_budget_drops_everything(self) -> None:
        kept, truncated = fit_block([_hit(ReflectionScope.PROJECT, "x")], max_chars=0)

        assert kept == []
        assert truncated is True

    def test_empty_input_is_not_truncated(self) -> None:
        assert fit_block([], max_chars=100) == ([], False)


class TestRenderBlock:
    def test_empty_returns_empty_string(self) -> None:
        assert render_block([]) == ""

    def test_renders_title_and_scope_labels_in_chinese(self) -> None:
        block = render_block(
            [_hit(ReflectionScope.PROJECT, "用 pnpm"), _hit(ReflectionScope.GLOBAL, "偏好结构化")],
            "zh-CN",
        )

        assert "历史经验" in block
        assert "- [项目] 用 pnpm" in block
        assert "- [全局] 偏好结构化" in block

    def test_renders_english_labels(self) -> None:
        block = render_block([_hit(ReflectionScope.PROJECT, "use pnpm")], "en")

        assert "Past lessons" in block
        assert "- [project] use pnpm" in block
