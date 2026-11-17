"""Metrics 模块独立功能 E2E：多维聚合、阈值规则、告警生命周期与开关。"""

from __future__ import annotations

from typing import Any

import pytest
from helpers import SAMPLE_PROJECT, FakeStack, make_event, seed_trace

from conftest import patch_obs
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import (
    AggregateQuery,
    MetricPoint,
    MetricSeries,
)
from devprompt_ai.domain.obs.metrics.rules import MetricThresholds, evaluate
from devprompt_ai.memory.metrics_alert_store import SQLiteAlertStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.registry import build_obs_modules


async def test_mt01_aggregates_all_dimensions(modules: Any, trace_store: SQLiteTraceStore) -> None:
    """MT-01：kind/name/model/turn/status 五维与时间桶聚合正确。"""
    await trace_store.append_events(
        seed_trace(
            trace_store,
            trace_id="s1:0:req",
            session_id="s1",
            turn_index=0,
            run_id="req",
            count=20,
            kinds=["tool.result", "llm.response"],
        )
    )
    for dimension in ("kind", "name", "model", "turn", "status"):
        series = await modules.metrics.summary(AggregateQuery(session_id="s1", group_by=dimension))
        assert series, f"{dimension} 维度无数据"
        assert all(item.dimension == dimension for item in series)
        assert sum(point.count for item in series for point in item.points) == 20

    by_kind = await modules.metrics.summary(AggregateQuery(session_id="s1", group_by="kind"))
    tool = next(item for item in by_kind if item.key == "tool.result")
    assert tool.points[0].p95_ms is not None

    bucketed = await modules.metrics.summary(
        AggregateQuery(session_id="s1", group_by="kind", bucket="minute")
    )
    assert all(point.bucket for item in bucketed for point in item.points)


def test_mt02_rule_thresholds_and_severity() -> None:
    """MT-02：四条规则触发边界与 critical 倍率。"""
    series = [
        MetricSeries(
            dimension="kind",
            key="action.end",
            points=(
                MetricPoint(
                    bucket="",
                    count=10,
                    failed=5,
                    avg_ms=6000.0,
                    p50_ms=5000,
                    p95_ms=11000,
                    p99_ms=12000,
                    tokens=0,
                ),
            ),
        ),
        MetricSeries(
            dimension="kind",
            key="tool.result",
            points=(
                MetricPoint(
                    bucket="",
                    count=4,
                    failed=2,
                    avg_ms=10.0,
                    p50_ms=10,
                    p95_ms=10,
                    p99_ms=10,
                    tokens=0,
                ),
            ),
        ),
        MetricSeries(
            dimension="kind",
            key="llm.response",
            points=(
                MetricPoint(
                    bucket="",
                    count=1,
                    failed=0,
                    avg_ms=10.0,
                    p50_ms=10,
                    p95_ms=10,
                    p99_ms=10,
                    tokens=60000,
                ),
            ),
        ),
    ]
    drafts = evaluate(
        series,
        MetricThresholds(),
        scope_kind="session",
        scope_key="s1",
    )
    by_rule = {draft.rule_id: draft for draft in drafts}
    assert set(by_rule) == {"p95_duration", "error_rate", "token_budget", "tool_failure_rate"}
    assert by_rule["p95_duration"].severity == "critical", "11000 > 5000*2"
    assert by_rule["error_rate"].severity == "critical", "7/15 ≈ 46.7% > 0.2*2"

    none = evaluate([], MetricThresholds(), scope_kind="session", scope_key="s1")
    assert none == []


async def test_mt03_alert_lifecycle(tmp_path: Any) -> None:
    """MT-03：active 新增/更新 → 条件消失 resolved，冷却字段存在。"""
    from devprompt_ai.domain.obs.contract.query import AlertDraft

    store = SQLiteAlertStore(str(tmp_path / "alerts.db"), cooldown_s=300)
    await store.init_schema()
    draft = AlertDraft(
        rule_id="p95_duration",
        severity="warning",
        scope_kind="session",
        scope_key="s1",
        metric="p95_ms",
        observed=9000.0,
        threshold=5000.0,
        message="p95 超限",
    )
    await store.sync_alerts([draft], scope_kind="session", scope_key="s1")
    active = await store.list_alerts(status="active")
    assert len(active) == 1
    assert active[0].cooldown_until != ""

    await store.sync_alerts([draft], scope_kind="session", scope_key="s1")
    assert len(await store.list_alerts(status="active")) == 1, "重复评估不得重复插入"

    await store.sync_alerts([], scope_kind="session", scope_key="s1")
    assert await store.list_alerts(status="active") == []
    resolved = await store.list_alerts(status="resolved")
    assert len(resolved) == 1 and resolved[0].resolved_at != ""


async def test_mt04_concurrent_evaluation_is_idempotent(
    modules: Any, trace_store: SQLiteTraceStore
) -> None:
    """MT-04（D-03）：同 scope 并发评估不产生唯一索引冲突。"""
    import asyncio

    events = []
    for index in range(1, 11):
        events.append(
            make_event(
                index,
                "action.end",
                session_id="s4",
                trace_id="s4:0:req",
                duration_ms=9000,
                status="failed" if index % 2 == 0 else "ok",
            )
        )
    await trace_store.append_events(events)
    await asyncio.gather(
        modules.metrics.evaluate(session_id="s4"),
        modules.metrics.evaluate(session_id="s4"),
        modules.metrics.evaluate(session_id="s4"),
    )
    alerts = await modules.metrics.alerts(status="active")
    assert alerts
    keys = [(alert.rule_id, alert.scope_kind, alert.scope_key) for alert in alerts]
    assert len(keys) == len(set(keys)), "活跃告警必须唯一"


async def test_mt05_empty_data(modules: Any) -> None:
    """MT-05：空数据不产生序列与告警。"""
    series = await modules.metrics.summary(AggregateQuery(session_id="empty", group_by="kind"))
    assert series == []
    await modules.metrics.evaluate(session_id="empty")
    assert await modules.metrics.alerts(status="active") == []


async def test_mt06_disabled_module_returns_6004(
    tmp_path: Any, api_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MT-06：模块关闭时 API 返回 6004。"""
    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=str(tmp_path / "off.db"),
        obs_metrics_enabled=False,
    )
    modules = build_obs_modules(cfg)
    await modules.startup()
    patch_obs(monkeypatch, modules)
    resp = await api_client.get("/api/v1/obs/metrics/config")
    assert resp.status_code == 404
    assert resp.json()["code"] == 6004


async def test_mt07_fake_run_metrics_cover_session(modules: Any, stack: FakeStack) -> None:
    """MT-07：一次 fake 运行的指标可按会话聚合，且告警评估可落库。"""
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-metrics",
    )
    await stack.collector.flush_all()
    await modules.metrics.evaluate(session_id=snapshot.session_id)

    series = await modules.metrics.summary(
        AggregateQuery(session_id=snapshot.session_id, group_by="kind")
    )
    assert series
    assert sum(point.count for item in series for point in item.points) > 0
    config = modules.metrics.config_payload()
    assert config["p95_ms_warn"] == 5000


async def test_mt08_alert_reopens_after_resolution(tmp_path: Any) -> None:
    """MT-08（D-03）：告警 resolved 后再次触发可重新进入 active 并再次恢复。"""
    from devprompt_ai.domain.obs.contract.query import AlertDraft

    store = SQLiteAlertStore(str(tmp_path / "alerts-reopen.db"), cooldown_s=0)
    await store.init_schema()
    draft = AlertDraft(
        rule_id="p95_duration",
        severity="warning",
        scope_kind="session",
        scope_key="s8",
        metric="p95_ms",
        observed=9000.0,
        threshold=5000.0,
        message="p95 超限",
    )
    for round_index in range(2):
        await store.sync_alerts([draft], scope_kind="session", scope_key="s8")
        assert len(await store.list_alerts(status="active")) == 1, f"第 {round_index} 轮"
        await store.sync_alerts([], scope_kind="session", scope_key="s8")
        assert await store.list_alerts(status="active") == [], f"第 {round_index} 轮"
