"""性能门槛 E2E：采集延迟、查询响应与数据完整率。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from helpers import make_event, percentile, seed_trace

from conftest import patch_obs
from devprompt_ai.domain.obs.contract.trace import TraceKind
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.memory.trace_store import SQLiteTraceStore

pytestmark = [pytest.mark.e2e, pytest.mark.perf]


def _p95(values: list[float]) -> float:
    return percentile(values, 95)


async def test_pf01_collection_latency_under_200ms(trace_store: SQLiteTraceStore) -> None:
    """PF-01：单事件采集（record→flush→可查）P95 ≤200ms。"""
    collector = TraceCollectorImpl(trace_store, buffer_size=1)
    await collector.start_turn(
        session_id="perf-collect",
        turn_id="t",
        turn_index=0,
        sentence="perf",
        project_root=".",
    )
    samples: list[float] = []
    for index in range(200):
        started = time.perf_counter()
        event_id = await collector.record(
            TraceKind.TOOL.value,
            "command",
            input={"index": index, "args": ["rg", "x"]},
            output={"stdout": "ok"},
        )
        await collector.flush()
        event = await trace_store.get_event(event_id)
        samples.append((time.perf_counter() - started) * 1000)
        assert event is not None
    assert _p95(samples) <= 200, f"采集 P95 超限：{_p95(samples):.1f}ms"

    batch_samples: list[float] = []
    for batch in range(50):
        events = [
            make_event(
                index,
                TraceKind.ACTION_END.value,
                trace_id=f"perf-batch-{batch}",
                session_id="perf-batch",
            )
            for index in range(1, 21)
        ]
        started = time.perf_counter()
        await trace_store.append_events(events)
        batch_samples.append((time.perf_counter() - started) * 1000)
    assert _p95(batch_samples) <= 200, f"批量写 P95 超限：{_p95(batch_samples):.1f}ms"


async def test_pf02_query_latency_under_500ms(
    modules: Any, trace_store: SQLiteTraceStore, api_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PF-02：5000 条 Trace 事件下 5 个只读端点 P95 ≤500ms。"""
    trace_ids: list[str] = []
    for index in range(100):
        trace_id = f"perf:{index}:req"
        trace_ids.append(trace_id)
        await trace_store.append_events(
            seed_trace(
                trace_store,
                trace_id=trace_id,
                session_id="perf",
                turn_index=index,
                run_id=f"req-{index}",
                count=50,
                kinds=["tool.result", "llm.response", "action.end"],
            )
        )
    patch_obs(monkeypatch, modules)
    paths = [
        "/api/v1/obs/trace/sessions/perf/traces?limit=200",
        "/api/v1/obs/trace/sessions/perf/events?limit=200",
        f"/api/v1/obs/trace/traces/{trace_ids[0]}?full=false",
        "/api/v1/obs/metrics/summary?session_id=perf&group_by=kind",
        "/api/v1/obs/metrics/alerts?status=active",
    ]
    samples: list[float] = []
    for _ in range(30):
        for path in paths:
            started = time.perf_counter()
            resp = await api_client.get(path)
            samples.append((time.perf_counter() - started) * 1000)
            assert resp.status_code == 200
    assert len(samples) == 150
    assert _p95(samples) <= 500, f"查询 P95 超限：{_p95(samples):.1f}ms"


async def test_pf03_completeness_at_least_99_9(trace_store: SQLiteTraceStore) -> None:
    """PF-03：10000 条合成事件写读一致，完整率 ≥99.9%。"""
    inserted = 0
    for trace_index in range(100):
        events = [
            make_event(
                seq,
                TraceKind.ACTION_END.value,
                trace_id=f"complete:{trace_index}:req",
                session_id="complete",
            )
            for seq in range(1, 101)
        ]
        await trace_store.append_events(events)
        inserted += len(events)

    read = 0
    for trace_index in range(100):
        read += len(await trace_store.list_trace_events(f"complete:{trace_index}:req"))
    completeness = read / inserted
    assert inserted == 10000
    assert completeness >= 0.999, f"完整率 {completeness:.4f}"
