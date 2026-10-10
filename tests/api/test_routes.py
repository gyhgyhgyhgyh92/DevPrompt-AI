"""Web 路由薄壳测试（httpx ASGI 内存传输 + Fake service，无真实 I/O）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.interfaces.api import health, routes
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.service import FlowSnapshot, RankingView, SnapshotStatus


def _snap(
    status: SnapshotStatus = "ask", state: str = "ASKING", session_id: str = "s1"
) -> FlowSnapshot:
    return FlowSnapshot(session_id=session_id, status=status, state=state)


class FakeForgeService:
    """仅实现路由触达的 service 方法；快照与失败可编程（复用 service 测试的 Fake 模式）。"""

    def __init__(self) -> None:
        self.status: SnapshotStatus = "ask"
        self.state: str = "ASKING"
        self.fail_with: StateError | None = None
        self.snapshot_override: FlowSnapshot | None = None
        self.feedback_calls: list[dict[str, Any]] = []
        self.scan: dict[str, Any] = {
            "total_symbols": 3,
            "total_files": 2,
            "kind_counts": {"function": 2, "class": 1},
        }

    async def optimize(
        self, user_id: str, project_root: str, sentence: str, *, request_id: str
    ) -> FlowSnapshot:
        return self._next()

    async def ask_followup(
        self, user_id: str, session_id: str, answers: dict[str, str], *, request_id: str
    ) -> FlowSnapshot:
        return self._next()

    async def escape(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        return FlowSnapshot(session_id=session_id, status="done", state="DONE")

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FlowSnapshot:
        return FlowSnapshot(session_id=session_id, status="ask", state="ASKING")

    async def resume(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        return self._next(session_id)

    async def get_preference(self, user_id: str) -> dict[str, float]:
        return {
            "detail_level": 0.5,
            "include_diff": 0.5,
            "specify_tests": 0.5,
            "max_files_norm": 0.5,
        }

    async def feedback(
        self,
        user_id: str,
        session_id: str,
        action: str,
        *,
        request_id: str,
        variant: str | None = None,
        edited_text: str | None = None,
    ) -> None:
        self.feedback_calls.append(
            {
                "session_id": session_id,
                "action": action,
                "variant": variant,
                "edited_text": edited_text,
                "request_id": request_id,
            }
        )
        return None

    async def scan_project(self, project_root: str) -> dict[str, Any]:
        return dict(self.scan)

    def _next(self, session_id: str = "s1") -> FlowSnapshot:
        if self.fail_with is not None:
            raise self.fail_with
        if self.snapshot_override is not None:
            return self.snapshot_override
        return _snap(self.status, self.state, session_id)


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> FakeForgeService:
    fake = FakeForgeService()

    async def _fake_get_service() -> FakeForgeService:
        return fake

    monkeypatch.setattr(routes, "get_service", _fake_get_service)
    return fake


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_health_checks_non_empty(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    async def fake_run_command(args: list[str], **kw: Any) -> str:
        return "ripgrep 14.1.0 (mock)"

    monkeypatch.setattr(health, "run_command", fake_run_command)
    monkeypatch.setenv("LLM_BASE_URL", "https://mock.local")
    monkeypatch.setenv("LLM_MODEL", "mock-model")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "devprompt.db"))
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    names = {c["name"] for c in data["checks"]}
    assert data["checks"]
    assert {"llm_config", "rg", "ctags", "git", "db_writable"} <= names
    assert data["is_healthy"] is True


async def test_optimize_returns_snapshot(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.post(
        "/api/v1/optimize", json={"sentence": "把提交按钮改成 primary-500", "project": "."}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["session_id"] == "s1"
    assert body["data"]["status"] == "ask"
    assert body["request_id"]
    assert fake_service.state == "ASKING"


async def test_optimize_missing_fields_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/optimize", json={})
    assert resp.status_code == 422


async def test_followup_answers_mode(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "done"
    fake_service.state = "DONE"
    resp = await client.post("/api/v1/followup/s1", json={"answers": {"test_file_exists": "有"}})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "done"


async def test_followup_escape_mode(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.post("/api/v1/followup/s1", json={"escape": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "DONE"


async def test_followup_guardrail_mode(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.post("/api/v1/followup/s1", json={"guardrail_action": "continue"})
    assert resp.status_code == 200
    assert resp.json()["data"]["state"] == "ASKING"


async def test_followup_modes_mutually_exclusive(client: httpx.AsyncClient) -> None:
    both = await client.post("/api/v1/followup/s1", json={"answers": {"k": "v"}, "escape": True})
    assert both.status_code == 422
    none_mode = await client.post("/api/v1/followup/s1", json={})
    assert none_mode.status_code == 422


async def test_result_reads_snapshot(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.get("/api/v1/result/s1")
    assert resp.status_code == 200
    assert resp.json()["data"]["session_id"] == "s1"


async def test_feedback_and_preference_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.post("/api/v1/feedback", json={"session_id": "s1", "action": "accept"})
    assert resp.status_code == 200
    pref = await client.get("/api/v1/preference")
    assert pref.status_code == 200
    assert pref.json()["data"]["detail_level"] == 0.5


async def test_feedback_variant_edited_text_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.post(
        "/api/v1/feedback",
        json={
            "session_id": "s1",
            "action": "accept",
            "variant": "C",
            "edited_text": "编辑后的方案正文",
        },
    )
    assert resp.status_code == 200
    assert fake_service.feedback_calls == [
        {
            "session_id": "s1",
            "action": "accept",
            "variant": "C",
            "edited_text": "编辑后的方案正文",
            "request_id": fake_service.feedback_calls[0]["request_id"],
        }
    ]


async def test_snapshot_renders_variants_and_ranking(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "done"
    fake_service.state = "DONE"
    fake_service.snapshot_override = FlowSnapshot(
        session_id="s1",
        status="done",
        state="DONE",
        ranking=RankingView(
            variant="B",
            gap=0.2,
            confidence=0.9,
            marked=True,
            reason="分差较小",
            fit=0.75,
            pref=0.88,
            total=0.802,
        ),
    )
    resp = await client.get("/api/v1/result/s1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["variants"] == []  # 未注入方案时默认空表
    assert data["ranking"] is not None
    assert data["ranking"]["variant"] == "B"
    assert data["ranking"]["marked"] is True
    assert "variant" not in data  # 旧单数字段已删除（BREAKING）


async def test_not_implemented_endpoints_501(client: httpx.AsyncClient) -> None:
    put_resp = await client.put("/api/v1/preference")
    assert put_resp.status_code == 501
    assert put_resp.json()["code"] == 9004
    history_resp = await client.get("/api/v1/history")
    assert history_resp.status_code == 501
    assert history_resp.json()["code"] == 9004


async def test_project_scan(client: httpx.AsyncClient, fake_service: FakeForgeService) -> None:
    resp = await client.get("/api/v1/project/scan", params={"project": "."})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_symbols"] == 3
    assert data["total_files"] == 2
    assert data["kind_counts"]["function"] == 2


async def test_error_response_uniform_shape(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.fail_with = StateError("流程 ID 不存在", code=6003)
    resp = await client.post("/api/v1/optimize", json={"sentence": "改按钮", "project": "."})
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 6003
    assert body["message"] == "流程 ID 不存在"
    assert body["request_id"]
    serialized = json.dumps(body)
    assert "stack" not in serialized and "traceback" not in serialized
    assert "detail" not in body  # FastAPI 默认错误键已被统一渲染替换


async def _collect_sse(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def test_sse_progress_ends_on_asking(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "ask"
    fake_service.state = "ASKING"
    events = await _collect_sse(client, "/api/v1/progress/s1")
    assert len(events) >= 1
    assert events[-1]["state"] == "ASKING"


async def test_sse_progress_ends_on_done(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "done"
    fake_service.state = "DONE"
    events = await _collect_sse(client, "/api/v1/progress/s1")
    assert len(events) >= 1
    assert events[-1]["state"] == "DONE"
