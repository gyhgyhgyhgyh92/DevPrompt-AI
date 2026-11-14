"""Web 路由薄壳测试（httpx ASGI 内存传输 + Fake service，无真实 I/O）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.domain.generate.ports import VariantDraft
from devprompt_ai.domain.models import Page, SessionSummary, TurnRecord
from devprompt_ai.domain.progress import ActionInfo, ProgressEvent
from devprompt_ai.interfaces.api import health, routes
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.service import FlowSnapshot, SnapshotStatus


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
        self.delete_project_calls: list[str] = []
        self.turns: list[TurnRecord] = []
        self.optimize_calls: list[dict[str, Any]] = []
        self.settings_view: dict[str, Any] = {
            "models": [
                {
                    "id": "m-1",
                    "provider_id": "p-1",
                    "provider": "DeepSeek",
                    "model_id": "mock-model",
                    "is_active": True,
                }
            ],
            "provider_configs": [
                {
                    "id": "p-1",
                    "provider": "DeepSeek",
                    "base_url": "https://mock.local",
                    "api_key_masked": "sk-••••3f7a",
                }
            ],
            "model_service": {
                "provider": "DeepSeek",
                "base_url": "https://mock.local",
                "api_key_masked": "sk-••••3f7a",
                "model_id": "mock-model",
                "timeout": 60.0,
                "temperature": None,
                "max_tokens": None,
            },
            "process": {
                "followup_soft_round_guard": 10,
                "followup_cost_budget": 0.0,
                "telemetry": True,
            },
            "observability": {
                "trace_enabled": True,
                "trace_retention_days": 30,
                "metrics_enabled": True,
                "replay_enabled": True,
            },
            "locked": {"candidate_limit": 25},
        }
        self.scan: dict[str, Any] = {
            "total_symbols": 3,
            "total_files": 2,
            "kind_counts": {"function": 2, "class": 1},
        }

    async def optimize(
        self,
        user_id: str,
        project_root: str,
        sentence: str,
        *,
        request_id: str,
        progress: Any = None,
        session_id: str | None = None,
        base_turn_id: str = "",
        locale: str = "zh-CN",
        domain_override: str | None = None,
        style: str | None = None,
        images: list[str] | None = None,
    ) -> FlowSnapshot:
        self.optimize_calls.append(
            {
                "session_id": session_id,
                "sentence": sentence,
                "base_turn_id": base_turn_id,
                "locale": locale,
            }
        )
        return self._next()

    async def ask_followup(
        self,
        user_id: str,
        session_id: str,
        answers: dict[str, str],
        *,
        request_id: str,
        progress: Any = None,
    ) -> FlowSnapshot:
        # 流式端点测试用：主动推一帧文字 + 一帧失败动作（2026-11-04）
        if progress is not None:
            await progress.emit(ProgressEvent(text="正在根据你的答复重新研判", phase="CONFIRMING"))
            await progress.emit(
                ProgressEvent(
                    action=ActionInfo(
                        title="检索符号",
                        detail="rg -n Foo --glob src",
                        scope="Exit code 1",
                        output="src: no match",
                        status="failed",
                    ),
                    phase="CONFIRMING",
                )
            )
        return self._next()

    async def escape(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        return FlowSnapshot(session_id=session_id, status="done", state="DONE")

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FlowSnapshot:
        return FlowSnapshot(session_id=session_id, status="ask", state="ASKING")

    async def resume(self, user_id: str, session_id: str, *, request_id: str) -> FlowSnapshot:
        return self._next(session_id)

    async def get_preference(
        self, user_id: str, *, request_id: str = ""
    ) -> tuple[dict[str, float], bool]:
        return (
            {
                "detail_level": 0.5,
                "include_diff": 0.5,
                "specify_tests": 0.5,
                "max_files_norm": 0.5,
            },
            False,
        )

    async def set_preference(self, user_id: str, values: dict[str, float]) -> dict[str, float]:
        self.preference_updates.append(dict(values))
        merged, _ = await self.get_preference(user_id)
        merged.update(values)
        return merged

    async def list_history(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> Page[SessionSummary]:
        return Page(
            items=(
                SessionSummary(
                    session_id="s1",
                    state="DONE",
                    project="demo",
                    updated_at="2026-10-12T00:00:00Z",
                    title="示例标题",
                    pinned=True,
                    project_root="/tmp/demo",
                ),
            ),
            has_more=False,
            limit=limit,
            offset=offset,
        )

    async def list_turns(
        self, user_id: str, session_id: str, *, limit: int = 20, offset: int = 0
    ) -> Page[TurnRecord]:
        return Page(
            items=tuple(self.turns),
            has_more=False,
            limit=limit,
            offset=offset,
        )

    async def load_turn(self, user_id: str, turn_id: str) -> TurnRecord:
        for turn in self.turns:
            if turn.turn_id == turn_id:
                return turn
        raise StateError("轮次不存在", code=6003)

    async def rename_session(self, user_id: str, session_id: str, title: str) -> None:
        self.rename_calls.append((session_id, title))

    async def pin_session(self, user_id: str, session_id: str, pinned: bool) -> None:
        self.pin_calls.append((session_id, pinned))

    async def delete_session(self, user_id: str, session_id: str) -> None:
        self.delete_calls.append(session_id)

    async def delete_project_sessions(self, user_id: str, project_root: str) -> int:
        self.delete_project_calls.append(project_root)
        return 2

    async def get_settings(self, locale: str = "zh-CN") -> dict[str, Any]:
        return dict(self.settings_view)

    async def update_settings(
        self, update: dict[str, Any], *, request_id: str = ""
    ) -> dict[str, Any]:
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


async def test_optimize_writes_session_log(
    client: httpx.AsyncClient,
    fake_service: FakeForgeService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """D-05：旧入口 /optimize 也写 run_events（Session Log 不再有盲区）。"""
    from types import SimpleNamespace

    from devprompt_ai.interfaces.api import runtime_routes
    from devprompt_ai.memory.event_store import SQLiteEventStore
    from devprompt_ai.runtime.events import EventBus

    bus = EventBus(SQLiteEventStore(str(tmp_path / "events.db")))

    async def _fake_bundle() -> Any:
        return SimpleNamespace(bus=bus)

    monkeypatch.setattr(runtime_routes, "_bundle", _fake_bundle)
    fake_service.config = object()  # type: ignore[attr-defined]  # 让路由认为运行时可用

    resp = await client.post(
        "/api/v1/optimize",
        json={"sentence": "改按钮", "project": ".", "session_id": "s1"},
    )
    assert resp.status_code == 200
    events = await bus.replay("s1", 0)
    assert [event.type for event in events] == ["run.started", "snapshot", "stop"]
    assert events[0].payload["request_id"] == resp.json()["request_id"]


async def test_optimize_forwards_accept_language(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """界面语言经 Accept-Language 解析后传给 service（2026-11-06，F-209 后端双语）。"""
    await client.post(
        "/api/v1/optimize",
        json={"sentence": "改按钮", "project": "."},
        headers={"accept-language": "en-US,en;q=0.9"},
    )
    assert fake_service.optimize_calls[-1]["locale"] == "en"

    # 无头（或未知语言）回落 zh-CN，不报错也不变成第三种语言
    await client.post("/api/v1/optimize", json={"sentence": "改按钮", "project": "."})
    assert fake_service.optimize_calls[-1]["locale"] == "zh-CN"


async def test_optimize_missing_fields_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/optimize", json={})
    assert resp.status_code == 422


async def test_followup_answers_mode(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "done"
    fake_service.state = "DONE"
    resp = await client.post(
        "/api/v1/followup/s1", json={"answers": {"请确认 test_file_exists": "有"}}
    )
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


async def test_snapshot_renders_single_variant(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.status = "done"
    fake_service.state = "DONE"
    fake_service.snapshot_override = FlowSnapshot(
        session_id="s1",
        status="done",
        state="DONE",
        variant=VariantDraft(
            title="标准版方案",
            body="正文",
            changes=[],
            fallback=False,
        ),
    )
    resp = await client.get("/api/v1/result/s1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["variant"]["title"] == "标准版方案"
    assert data["variant"]["fallback"] is False
    # 旧契约字段已删除（BREAKING，2026-11-11 单套输出）
    assert "variants" not in data
    assert "ranking" not in data
    assert "ranking_skip_reason" not in data


async def test_get_history_returns_summaries(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """T6-11/T1.4：GET /history 仅 id/时间/state/名/路径/标题/置顶（无原句明文，MUST-19）。"""
    resp = await client.get("/api/v1/history")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == [
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
    assert data["has_more"] is False
    assert "sentence" not in data["items"][0]


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


async def test_followup_stream_ends_with_snapshot_frame(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """流式答复端点（2026-11-03）：SSE 帧以 snapshot 收尾（此前只有一次性 JSON）。"""
    resp = await client.post(
        "/api/v1/followup/s1/stream", json={"answers": {"请确认 q": "a"}, "escape": False}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type": "snapshot"' in resp.text


async def test_followup_stream_frame_order_and_action_fields(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """帧顺序契约（2026-11-04）：thought → action → snapshot，snapshot 必须是最后一帧。

    同时校验动作帧字段白名单与失败态（status/Exit code 由后端给出，前端只渲染）。
    """
    resp = await client.post(
        "/api/v1/followup/s1/stream", json={"answers": {"请确认 q": "a"}, "escape": False}
    )

    frames = [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [frame["type"] for frame in frames]

    assert types == ["thought", "action", "snapshot"]
    assert types[-1] == "snapshot"
    assert "snapshot" not in types[:-1]

    action = frames[1]
    assert action["status"] == "failed"
    assert action["scope"] == "Exit code 1"
    # duration_ms（2026-11-07）：未计时的动作下发 None，前端据此不渲染耗时
    assert set(action) == {
        "type",
        "phase",
        "title",
        "detail",
        "scope",
        "output",
        "status",
        "duration_ms",
    }
    assert action["duration_ms"] is None
    # 帧里不得出现绝对路径（MUST-19）
    assert "D:/" not in json.dumps(action, ensure_ascii=False)


async def test_delete_history_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.delete("/api/v1/history/s1")
    assert resp.status_code == 200
    assert resp.json()["data"] is None
    assert fake_service.delete_calls == ["s1"]


async def test_delete_project_history_passthrough(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """项目级批量删除（2026-11-01）：query 透传 project_root，返回实际删除条数。"""
    resp = await client.delete("/api/v1/history", params={"project_root": "/tmp/demo"})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": 2}
    assert fake_service.delete_project_calls == ["/tmp/demo"]


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
    # 多模型注册表视图（F-604，2026-10-13）：2026-10-18 起密钥在供应商段，条目只引用
    assert data["models"][0]["id"] == "m-1"
    assert data["models"][0]["provider_id"] == "p-1"
    assert data["models"][0]["is_active"] is True
    assert data["provider_configs"][0]["api_key_masked"] == "sk-••••3f7a"
    assert "api_key_masked" not in data["models"][0]

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
    """PUT /settings 供应商段 + 条目段透传：原样交 service（2026-10-18 供应商中心化）。"""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "provider_configs": [{"id": "p-1", "provider": "DeepSeek", "base_url": "https://a"}],
            "models": [{"id": "m-1", "provider_id": "p-1", "model_id": "deepseek-flash"}],
            "active_model_id": "m-1",
        },
    )
    assert resp.status_code == 200
    assert fake_service.settings_updates[-1] == {
        "provider_configs": [{"id": "p-1", "provider": "DeepSeek", "base_url": "https://a"}],
        "models": [{"id": "m-1", "provider_id": "p-1", "model_id": "deepseek-flash"}],
        "active_model_id": "m-1",
    }


async def test_project_scan(client: httpx.AsyncClient, fake_service: FakeForgeService) -> None:
    resp = await client.get("/api/v1/project/scan", params={"project": "."})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_symbols"] == 3
    assert data["total_files"] == 2
    assert data["kind_counts"]["function"] == 2


async def test_session_turns_are_summaries_only(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    """轮次列表只给摘要：不含原句与方案正文（正文懒加载走 /turns/{id}）。"""
    fake_service.turns = [
        TurnRecord(
            turn_id="t1",
            session_id="s1",
            turn_index=0,
            state="DONE",
            input="把按钮改成红色",
            output=[{"title": "x", "body": "正文", "changes": []}],
            summary={"target": "Button", "conclusion": "复用令牌", "open": ["对比度"]},
        )
    ]

    resp = await client.get("/api/v1/history/s1/turns")

    assert resp.status_code == 200
    data = resp.json()["data"]
    items = data["items"]
    assert [turn["turn_id"] for turn in items] == ["t1"]
    assert items[0]["target"] == "Button"
    assert items[0]["open_items"] == ["对比度"]
    assert "input" not in items[0]
    assert "variants" not in items[0]
    assert data["has_more"] is False


async def test_turn_detail_carries_body(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.turns = [
        TurnRecord(
            turn_id="t1",
            session_id="s1",
            turn_index=0,
            state="DONE",
            input="把按钮改成红色",
            output=[{"title": "保守版", "body": "改按钮", "changes": ["改色"]}],
            facts=[{"key": "token_defined", "passed": False, "evidence": "未找到"}],
        )
    ]

    resp = await client.get("/api/v1/turns/t1")

    body = resp.json()["data"]
    assert body["input"] == "把按钮改成红色"
    assert body["variants"][0]["body"] == "改按钮"
    assert body["facts"][0]["key"] == "token_defined"


async def test_missing_turn_returns_6003(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    resp = await client.get("/api/v1/turns/nope")

    assert resp.status_code == 200
    assert resp.json()["code"] == 6003


async def test_project_scan_failure_returns_envelope(
    client: httpx.AsyncClient,
    fake_service: FakeForgeService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫描失败必须回信封错误码，不能裸 500（否则前端只能猜「路径不存在」）。"""

    async def _boom(_project: str) -> dict[str, Any]:
        raise DevPromptError("项目路径不存在或不是目录", code=2001)

    monkeypatch.setattr(fake_service, "scan_project", _boom)
    resp = await client.get("/api/v1/project/scan", params={"project": "D:/nope"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 2001
    assert body["data"] is None
    assert body["request_id"]


async def test_error_response_uniform_shape(
    client: httpx.AsyncClient, fake_service: FakeForgeService
) -> None:
    fake_service.fail_with = StateError("流程 ID 不存在", code=6003)
    resp = await client.post("/api/v1/optimize", json={"sentence": "改按钮", "project": "."})
    # 6003 → 404（架构文档 §3.3 逐码表；2026-11-04 前一律 500）
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 6003
    assert body["message"] == "流程 ID 不存在"
    assert body["request_id"]
    serialized = json.dumps(body)
    assert "stack" not in serialized and "traceback" not in serialized
    assert "detail" not in body  # FastAPI 默认错误键已被统一渲染替换


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (1001, 400),
        (2001, 404),
        (2003, 500),
        (2005, 422),
        (3004, 429),
        (4002, 503),
        (5011, 503),
        (5014, 401),
        (6001, 409),
        (9001, 500),
    ],
)
async def test_error_http_status_follows_spec_table(
    client: httpx.AsyncClient, fake_service: FakeForgeService, code: int, status: int
) -> None:
    """HTTP 状态按架构文档 §3.3 逐码表映射，不再一律 500（2026-11-04）。"""
    fake_service.fail_with = StateError("x", code=code)

    resp = await client.post("/api/v1/optimize", json={"sentence": "改按钮", "project": "."})

    assert resp.status_code == status
    assert resp.json()["code"] == code


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
