"""POST /optimize/stream：思考过程 SSE 的帧顺序、终帧与保活（MUST-15 禁重试、MUST-19）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.progress import ActionInfo, ProgressEvent
from devprompt_ai.interfaces.api import routes
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.service import FlowSnapshot, SnapshotStatus


def _snapshot(status: SnapshotStatus = "done", state: str = "DONE") -> FlowSnapshot:
    return FlowSnapshot(session_id="s-stream", status=status, state=state)


class FakeStreamService:
    """只实现流式端点用到的 optimize（含 progress 出口）。"""

    def __init__(
        self,
        *,
        texts: list[str] | None = None,
        actions: list[ActionInfo] | None = None,
        fail: Exception | None = None,
        delay: float = 0.0,
        status: SnapshotStatus = "done",
        state: str = "DONE",
    ) -> None:
        self.texts = texts or []
        self.actions = actions or []
        self.fail = fail
        self.delay = delay
        self.snapshot = _snapshot(status, state)
        self.calls: list[dict[str, Any]] = []

    async def optimize(
        self,
        user_id: str,
        project_root: str,
        sentence: str,
        *,
        request_id: str,
        progress: Any = None,
        session_id: str | None = None,
        locale: str = "zh-CN",
    ) -> FlowSnapshot:
        self.calls.append(
            {"user_id": user_id, "project": project_root, "sentence": sentence, "rid": request_id}
        )
        for text in self.texts:
            if progress is not None:
                await progress.emit(ProgressEvent(text))
        for action in self.actions:
            if progress is not None:
                await progress.emit(ProgressEvent(action=action))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return self.snapshot


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeStreamService) -> FakeStreamService:
    async def _fake_get_service() -> FakeStreamService:
        return fake

    monkeypatch.setattr(routes, "get_service", _fake_get_service)
    return fake


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _frames(body: str) -> list[dict[str, Any]]:
    """按 SSE 空行分帧；注释帧（: ping）跳过。"""
    frames: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        frames.append(json.loads(block.removeprefix("data: ")))
    return frames


async def test_thoughts_then_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, FakeStreamService(texts=["先检索代码", "已选中目标"]))

    resp = await client.post(
        "/api/v1/optimize/stream", json={"sentence": "把按钮改成主色", "project": "."}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp.text)
    assert [frame["type"] for frame in frames] == ["thought", "thought", "snapshot"]
    assert [frame["text"] for frame in frames[:-1]] == ["先检索代码", "已选中目标"]
    assert frames[-1]["data"]["session_id"] == "s-stream"
    assert frames[-1]["data"]["status"] == "done"


async def test_ask_status_still_delivers_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反问分支（未知项）也走 snapshot 帧，前端据此切反问卡而非结果页。"""
    _patch(monkeypatch, FakeStreamService(texts=["有信息缺口"], status="ask", state="ASKING"))

    resp = await client.post("/api/v1/optimize/stream", json={"sentence": "改一下", "project": "."})

    last = _frames(resp.text)[-1]
    assert last["type"] == "snapshot"
    assert last["data"]["status"] == "ask"


async def test_action_frame_carries_card_payload(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """动作卡片是独立帧：title/detail/scope 平铺，前端据此渲染可折叠卡片。"""
    _patch(
        monkeypatch,
        FakeStreamService(
            texts=["先检索代码"],
            actions=[
                ActionInfo(title="检索符号", detail="rg -n Foo --glob src/a.ts", scope="命中 2 行")
            ],
        ),
    )

    resp = await client.post("/api/v1/optimize/stream", json={"sentence": "改一下", "project": "."})

    frames = _frames(resp.text)
    assert [frame["type"] for frame in frames] == ["thought", "action", "snapshot"]
    card = frames[1]
    assert card["title"] == "检索符号"
    assert card["scope"] == "命中 2 行"
    assert "output" in card
    assert card["detail"].startswith("rg -n Foo")


async def test_error_frame_carries_code_and_closes_stream(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, FakeStreamService(fail=DevPromptError("生成阶段失败", code=4001)))

    resp = await client.post("/api/v1/optimize/stream", json={"sentence": "改一下", "project": "."})

    frames = _frames(resp.text)
    assert frames[-1]["type"] == "error"
    assert frames[-1]["code"] == 4001
    assert frames[-1]["message"] == "生成阶段失败"
    assert frames[-1]["request_id"]


async def test_ping_keeps_stream_alive_during_slow_step(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "_STREAM_PING_SECONDS", 0.02)
    _patch(monkeypatch, FakeStreamService(delay=0.12))

    resp = await client.post("/api/v1/optimize/stream", json={"sentence": "改一下", "project": "."})

    assert ": ping" in resp.text
    assert _frames(resp.text)[-1]["type"] == "snapshot"


async def test_sentence_travels_in_body_not_url(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUST-19：原句不能出现在 URL / 访问日志里。"""
    fake = _patch(monkeypatch, FakeStreamService())
    sentence = "把提交按钮改成 primary-500 并且加禁用态"

    resp = await client.post(
        "/api/v1/optimize/stream", json={"sentence": sentence, "project": "D:/repo"}
    )

    assert resp.status_code == 200
    assert sentence not in str(resp.request.url)
    assert fake.calls[0]["sentence"] == sentence
    assert fake.calls[0]["project"] == "D:/repo"
