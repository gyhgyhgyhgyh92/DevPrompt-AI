"""三模块 API：独立开关 6004、Trace 查询、Metrics 配置与告警。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceKind
from devprompt_ai.interfaces.api import obs_common
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.registry import ObsModules, build_obs_modules


def _event(seq: int, kind: str, *, duration: int = 10, status: str = "ok") -> TraceEvent:
    return TraceEvent(
        event_id=f"e{seq}",
        trace_id="s1:0:req",
        session_id="s1",
        turn_id="turn1",
        turn_index=0,
        run_id="r1",
        seq=seq,
        parent_id="",
        kind=kind,
        name=kind,
        status=status,
        started_at=f"2026-11-12T10:00:{seq:02d}.000Z",
        ended_at=f"2026-11-12T10:00:{seq:02d}.500Z",
        duration_ms=duration,
        attributes={"model_id": "m1", "tokens": 100, "input_hash": "hash1"},
    )


class _FakeService:
    def __init__(self, modules: ObsModules) -> None:
        self.obs = modules
        self.config = modules.cfg


async def _build(tmp_path: Any, **update: Any) -> ObsModules:
    cfg = AppConfig(_env_file=None, db_path=str(tmp_path / "obs.db"), **update)  # type: ignore[call-arg]
    modules = build_obs_modules(cfg)
    await modules.startup()
    return modules


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _patch(monkeypatch: pytest.MonkeyPatch, modules: ObsModules) -> None:
    async def _fake_get_service() -> _FakeService:
        return _FakeService(modules)

    monkeypatch.setattr(obs_common, "get_service", _fake_get_service)


async def test_trace_api_lists_events_and_detail(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    modules = await _build(tmp_path)
    store = SQLiteTraceStore(modules.cfg.db_path)
    await store.append_events(
        [_event(1, TraceKind.TURN_START.value), _event(2, TraceKind.ACTION_END.value)]
    )
    _patch(monkeypatch, modules)

    traces = (await client.get("/api/v1/obs/trace/sessions/s1/traces")).json()
    assert traces["code"] == 0
    assert traces["data"]["items"][0]["trace_id"] == "s1:0:req"

    events = (await client.get("/api/v1/obs/trace/sessions/s1/events?limit=1")).json()
    assert events["data"]["has_more"] is True
    assert events["data"]["next_cursor"] == 1

    detail = (await client.get("/api/v1/obs/trace/traces/s1:0:req?full=true")).json()
    assert len(detail["data"]["items"]) == 2

    single = (await client.get("/api/v1/obs/trace/events/e1")).json()
    assert single["data"]["event"]["event_id"] == "e1"


async def test_modules_disabled_returns_6004(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    modules = await _build(
        tmp_path,
        obs_trace_enabled=False,
        obs_metrics_enabled=False,
        obs_replay_enabled=False,
    )
    _patch(monkeypatch, modules)

    for path in (
        "/api/v1/obs/trace/sessions/s1/traces",
        "/api/v1/obs/metrics/config",
        "/api/v1/obs/replay/runs/x",
    ):
        resp = await client.get(path)
        assert resp.status_code == 404
        assert resp.json()["code"] == 6004


async def test_metrics_config_and_alerts(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    modules = await _build(tmp_path)
    store = SQLiteTraceStore(modules.cfg.db_path)
    await store.append_events(
        [
            _event(1, TraceKind.TURN_START.value),
            _event(2, TraceKind.ACTION_END.value, duration=9000),
            _event(3, TraceKind.ACTION_END.value, duration=9000, status="failed"),
        ]
    )
    await modules.metrics.evaluate(session_id="s1")
    _patch(monkeypatch, modules)

    config = (await client.get("/api/v1/obs/metrics/config")).json()
    assert config["data"]["config"]["p95_ms_warn"] == 5000

    summary = (await client.get("/api/v1/obs/metrics/summary?session_id=s1&group_by=kind")).json()
    assert summary["data"]["items"]

    alerts = (await client.get("/api/v1/obs/metrics/alerts?status=active")).json()
    rules = {item["rule_id"] for item in alerts["data"]["items"]}
    assert "p95_duration" in rules
