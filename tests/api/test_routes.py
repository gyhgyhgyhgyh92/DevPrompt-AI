"""Web 路由薄壳测试（httpx ASGI 内存传输 + Fake service，无真实 I/O）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import SessionSummary
from devprompt_ai.harness.browse import BrowseEntry, BrowseListing
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
        self.preference_updates: list[dict[str, float]] = []
        self.settings_updates: list[dict[str, Any]] = []
        self.adoption_clear_calls: list[str] = []
        self.rename_calls: list[tuple[str, str]] = []
        self.pin_calls: list[tuple[str, bool]] = []
        self.delete_calls: list[str] = []
        self.settings_view: dict[str, Any] = {
            "models": [
                {
                    "id": "m-1",
                    "label": "DeepSeek · mock-model",
                    "provider": "DeepSeek",
                    "base_url": "https://mock.local",
                    "model_id": "mock-model",
                    "api_key_masked": "sk-••••3f7a",
                    "is_active": True,
                }
            ],
            "model_service": {
                "provider": "DeepSeek",
                "base_url": "https://mock.local",
                "api_key_masked": "sk-••••3f7a",
                "model_id": "mock-model",
                "decider": "fallback",
                "timeout": 60.0,
                "temperature": None,
                "max_tokens": None,
            },
            "process": {
                "followup_soft_round_guard": 10,
                "followup_cost_budget": 0.0,
                "telemetry": True,
            },
            "locked": {"candidate_limit": 25},
        }
        self.scan: dict[str, Any] = {
            "total_symbols": 3,
            "total_files": 2,
            "kind_counts": {"function": 2, "class": 1},
        }
        self.browse_listing: BrowseListing = BrowseListing(
            path="D:/ws/repo",
            parent="D:/ws",
            entries=(BrowseEntry(name="src", path="D:/ws/repo/src", modified_at=None),),
        )

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

    async def set_preference(self, user_id: str, values: dict[str, float]) -> dict[str, float]:
        self.preference_updates.append(dict(values))
        merged = await self.get_preference(user_id)
        merged.update(values)
        return merged

    async def list_history(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        return [
            SessionSummary(
                session_id="s1",
                state="DONE",
                project="demo",
                updated_at="2026-10-12T00:00:00Z",
                title="示例标题",
                pinned=True,
                project_root="/tmp/demo",
            )
        ]

    async def rename_session(self, user_id: str, session_id: str, title: str) -> None:
        self.rename_calls.append((session_id, title))

    async def pin_session(self, user_id: str, session_id: str, pinned: bool) -> None:
        self.pin_calls.append((session_id, pinned))

    async def delete_session(self, user_id: str, session_id: str) -> None:
        self.delete_calls.append(session_id)

    async def get_settings(self) -> dict[str, Any]:
        return dict(self.settings_view)

    async def update_settings(self, update: dict[str, Any]) -> dict[str, Any]:
        self.settings_updates.append(update)
        return dict(self.settings_view)

    async def clear_adoption_history(self, user_id: str) -> int:
        self.adoption_clear_calls.append(user_id)
        return 3

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

    async def browse_directory(self, path: str) -> BrowseListing:
        return self.browse_listing

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


async def test_put_preference_partial_update_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """T6-11 转正：PUT /preference 部分更新（None 字段过滤），契约体四维回读。"""
    resp = await client.put(
        "/api/v1/preference",
        json={"detail_level": 1.5, "specify_tests": -0.2, "include_diff": None},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"detail_level", "include_diff", "specify_tests", "max_files_norm"}
    # 路由层原值透传；clip01 截断归 service（见 tests/test_service.py）
    assert fake_service.preference_updates == [{"detail_level": 1.5, "specify_tests": -0.2}]


async def test_get_history_returns_summaries(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """T6-11/T1.4：GET /history 仅 id/时间/state/名/路径/标题/置顶（无原句明文，MUST-19）。"""
    resp = await client.get("/api/v1/history")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert items == [
        {
            "session_id": "s1",
            "state": "DONE",
            "project": "demo",
            "updated_at": "2026-10-12T00:00:00Z",
            "title": "示例标题",
            "pinned": True,
            "project_root": "/tmp/demo",
        }
    ]
    assert "sentence" not in items[0]


async def test_patch_history_rename_and_pin_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """T1.4：PATCH /history/{session_id} 透传 title/pinned，None 字段不提交。"""
    resp = await client.patch("/api/v1/history/s1", json={"title": "新标题", "pinned": True})
    assert resp.status_code == 200
    assert resp.json()["data"] is None
    assert fake_service.rename_calls == [("s1", "新标题")]
    assert fake_service.pin_calls == [("s1", True)]


async def test_patch_history_title_only_leaves_pinned_untouched(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.patch("/api/v1/history/s1", json={"title": "仅改标题"})
    assert resp.status_code == 200
    assert fake_service.rename_calls == [("s1", "仅改标题")]
    assert fake_service.pin_calls == []  # pinned=None → 不提交


async def test_patch_history_empty_422(client: httpx.AsyncClient) -> None:
    """title/pinned 均缺省 → 422（model_validator 拦截空更新）。"""
    resp = await client.patch("/api/v1/history/s1", json={})
    assert resp.status_code == 422


async def test_delete_history_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.delete("/api/v1/history/s1")
    assert resp.status_code == 200
    assert resp.json()["data"] is None
    assert fake_service.delete_calls == ["s1"]


async def test_settings_get_put_roundtrip(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """F-604：GET/PUT /settings；密钥恒脱敏形态，候选上限锁定只读（MUST-09）。"""
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["model_service"]["api_key_masked"] == "sk-••••3f7a"
    assert "api_key" not in data["model_service"]
    assert data["locked"]["candidate_limit"] == 25
    # 多模型注册表视图（F-604，2026-10-13）：条目 api_key 恒脱敏，is_active 标注当前生效项
    assert data["models"][0]["id"] == "m-1"
    assert data["models"][0]["api_key_masked"] == "sk-••••3f7a"
    assert data["models"][0]["is_active"] is True

    put_resp = await client.put(
        "/api/v1/settings",
        json={
            "model_service": {"api_key": "sk-new-secret-1234567890"},
            "process": {"telemetry": False},
        },
    )
    assert put_resp.status_code == 200
    assert fake_service.settings_updates == [
        {
            "model_service": {"api_key": "sk-new-secret-1234567890"},
            "process": {"telemetry": False},
        }
    ]


async def test_settings_put_models_and_activation_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """PUT /settings 多模型段透传（F-604）：models 与 active_model_id 原样交 service。"""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "models": [
                {
                    "id": "m-1",
                    "label": "A",
                    "provider": "DeepSeek",
                    "base_url": "https://a",
                    "model_id": "deepseek-flash",
                }
            ],
            "active_model_id": "m-1",
        },
    )
    assert resp.status_code == 200
    assert fake_service.settings_updates[-1] == {
        "models": [
            {
                "id": "m-1",
                "label": "A",
                "provider": "DeepSeek",
                "base_url": "https://a",
                "model_id": "deepseek-flash",
            }
        ],
        "active_model_id": "m-1",
    }


async def test_project_scan(client: httpx.AsyncClient, fake_service: FakeForgeService) -> None:
    resp = await client.get("/api/v1/project/scan", params={"project": "."})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_symbols"] == 3
    assert data["total_files"] == 2
    assert data["kind_counts"]["function"] == 2


async def test_project_browse_returns_listing(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """GET /project/browse：返回 path/parent/entries/truncated；X-Request-ID 头与信封一致。"""
    resp = await client.get("/api/v1/project/browse", params={"path": "D:/ws/repo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {
        "path": "D:/ws/repo",
        "parent": "D:/ws",
        "entries": [{"name": "src", "path": "D:/ws/repo/src", "modified_at": None}],
        "truncated": False,
    }
    assert resp.headers["x-request-id"] == body["request_id"]


async def test_project_browse_empty_path_returns_drives(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """无 path 参数：驱动器列表模式（path 空串 + parent null）。"""
    fake_service.browse_listing = BrowseListing(path="", parent=None)
    resp = await client.get("/api/v1/project/browse")
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "path": "",
        "parent": None,
        "entries": [],
        "truncated": False,
    }


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


async def test_x_request_id_header_matches_envelope(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """§3.1：X-Request-ID 响应头与信封 request_id 同值（全端点透传）。"""
    resp = await client.get("/api/v1/settings")
    assert resp.headers["x-request-id"] == resp.json()["request_id"]


async def test_x_request_id_echoed_from_request(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """客户端携带 X-Request-ID 时回显（链路追踪约定）。"""
    resp = await client.get("/api/v1/settings", headers={"X-Request-ID": "trace-123"})
    assert resp.headers["x-request-id"] == "trace-123"
    assert resp.json()["request_id"] == "trace-123"


async def test_delete_preference_adoptions(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """D-6F-4：DELETE /preference/adoptions 清空服务端采纳历史，返回清空条数。"""
    resp = await client.delete("/api/v1/preference/adoptions")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"cleared": 3}
    assert fake_service.adoption_clear_calls == ["local"]
