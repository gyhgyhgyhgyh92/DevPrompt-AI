"""真进程端到端：健康检查、请求 ID、错误码、事件日志、续跑拒绝。

这些用例不调用 LLM，可在 CI 稳定运行。
"""

from __future__ import annotations

import uuid

import pytest

from conftest import envelope


def test_health_is_ready(api) -> None:  # type: ignore[no-untyped-def]
    response = api.get("/api/v1/health")
    assert response.status_code == 200
    body = envelope(response)
    assert body["code"] == 0
    assert isinstance(body.get("data"), dict)


def test_request_id_is_echoed(api) -> None:  # type: ignore[no-untyped-def]
    rid = uuid.uuid4().hex
    response = api.get("/api/v1/health", headers={"X-Request-ID": rid})
    assert response.headers.get("X-Request-ID") == rid


def test_start_run_rejects_empty_input(api) -> None:  # type: ignore[no-untyped-def]
    response = api.post(
        "/api/v1/runs",
        json={"session_id": uuid.uuid4().hex, "project": "", "sentence": ""},
    )
    body = envelope(response)
    assert body["code"] != 0


def test_resume_unknown_run_returns_6003(api) -> None:  # type: ignore[no-untyped-def]
    response = api.post(f"/api/v1/runs/{uuid.uuid4().hex}/resume", json={"request_id": "r1"})
    body = envelope(response)
    assert body["code"] == 6003


def test_event_log_endpoint(api) -> None:  # type: ignore[no-untyped-def]
    response = api.get("/api/v1/obs/logs/events", params={"limit": 5})
    assert response.status_code == 200
    body = envelope(response)
    assert body["code"] == 0
    assert "items" in body["data"]


def test_obs_metrics_summary(api) -> None:  # type: ignore[no-untyped-def]
    response = api.get("/api/v1/obs/metrics/summary", params={"group_by": "kind"})
    assert response.status_code == 200
    assert envelope(response)["code"] == 0


@pytest.mark.parametrize("path", ["/api/v1/history", "/api/v1/settings"])
def test_read_only_endpoints(api, path: str) -> None:  # type: ignore[no-untyped-def]
    response = api.get(path)
    assert response.status_code == 200
    assert envelope(response)["code"] == 0
