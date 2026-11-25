"""Reflection 指标聚合（2026-11-23）：比率、样本量与 no-data。"""

from __future__ import annotations

from devprompt_ai.domain.obs.metrics.reflection import aggregate_reflection


def test_aggregates_answers_rounds_and_reflection_events() -> None:
    events = [
        {
            "event": "clarification.answer_classified",
            "total": 4,
            "option": 2,
            "best_guess": 1,
            "free_text": 1,
            "multi_select": 1,
        },
        {
            "event": "clarification.answer_classified",
            "total": 6,
            "option": 4,
            "best_guess": 1,
            "free_text": 1,
            "multi_select": 0,
        },
        {"event": "followup.expect_unmet", "repeated": 2, "total": 10},
        {"event": "followup.expect_unmet", "repeated": 1, "total": 5},
        {"event": "reflection.recalled", "hits": 2},
        {"event": "reflection.recalled", "hits": 0},
        {"event": "reflection.recorded", "scope": "project"},
        {"event": "reflection.recorded", "scope": "global"},
        {"event": "reflection.preference", "signals": 2},
        {"event": "unknown.event"},
    ]

    metrics = aggregate_reflection(events, session_rounds=[1, 0, 3])

    assert metrics.has_data is True
    assert metrics.sessions == 3
    assert metrics.rounds_sessions == 2
    assert metrics.avg_clarification_rounds == 2.0
    assert metrics.answer_total == 10
    assert metrics.free_text_ratio == 0.2
    assert metrics.option_ratio == 0.6
    assert metrics.best_guess_ratio == 0.2
    assert metrics.repeat_ask_rate == 0.2
    assert metrics.recall_hit_rate == 0.5
    assert metrics.recorded_project == 1
    assert metrics.recorded_global == 1
    assert metrics.preference_events == 1


def test_empty_input_is_no_data() -> None:
    metrics = aggregate_reflection([], session_rounds=[])

    assert metrics.has_data is False
    assert metrics.repeat_ask_rate is None
    assert metrics.avg_clarification_rounds is None
    assert metrics.free_text_ratio is None
    assert metrics.option_ratio is None
    assert metrics.best_guess_ratio is None
    assert metrics.recall_hit_rate is None


def test_missing_denominators_are_none_not_zero() -> None:
    metrics = aggregate_reflection([{"event": "reflection.recorded", "scope": "global"}])

    assert metrics.has_data is True
    assert metrics.answer_total == 0
    assert metrics.free_text_ratio is None
    assert metrics.recall_hit_rate is None
    assert metrics.avg_clarification_rounds is None
