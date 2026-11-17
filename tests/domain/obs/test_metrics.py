"""Metrics 聚合与阈值规则测试。"""

from __future__ import annotations

from devprompt_ai.domain.obs.contract.query import MetricPoint, MetricSeries
from devprompt_ai.domain.obs.metrics.aggregate import TraceRow, build_series, percentile
from devprompt_ai.domain.obs.metrics.rules import MetricThresholds, evaluate


def _row(kind: str, duration: int, status: str = "ok", tokens: int = 0) -> TraceRow:
    return TraceRow(
        kind=kind,
        name=kind,
        status=status,
        turn_index=0,
        model_id="m1",
        duration_ms=duration,
        tokens=tokens,
        started_at="2026-11-12T10:00:00.000Z",
    )


def test_percentile_linear_interpolation() -> None:
    assert percentile([], 50) is None
    assert percentile([10], 95) == 10
    assert percentile([10, 20, 30, 41], 50) == 25
    assert percentile([10, 20, 30, 41], 95) == 39


def test_build_series_groups_by_kind_and_bucket() -> None:
    series = build_series(
        [_row("action", 10), _row("action", 30, "failed"), _row("llm.response", 100)],
        dimension="kind",
        bucket="hour",
        percentiles=(50, 95),
    )

    by_key = {item.key: item for item in series}
    assert set(by_key) == {"action", "llm.response"}
    action = by_key["action"]
    assert action.points[0].count == 2
    assert action.points[0].failed == 1
    assert action.points[0].p50_ms == 20


def test_rules_trigger_and_severity() -> None:
    series = [
        MetricSeries(
            dimension="kind",
            key="action",
            points=(MetricPoint("", 10, 4, 6000.0, 6000, 12000, 12000, 0),),
        ),
        MetricSeries(
            dimension="kind",
            key="tool.result",
            points=(MetricPoint("", 5, 3, 10.0, 10, 10, 10, 0),),
        ),
    ]

    drafts = evaluate(
        series,
        MetricThresholds(p95_ms_warn=5000, error_rate_warn=0.2, tool_failure_rate_warn=0.2),
        scope_kind="session",
        scope_key="s1",
    )

    by_rule = {item.rule_id: item for item in drafts}
    assert by_rule["p95_duration"].severity == "critical"
    assert by_rule["error_rate"].observed == 7 / 15
    assert by_rule["tool_failure_rate"].severity == "critical"
    assert "token_budget" not in by_rule


def test_rules_empty_series_no_alert() -> None:
    assert evaluate([], MetricThresholds(), scope_kind="session", scope_key="s1") == []
