"""Session Log（运行时事件台账）独立功能 E2E。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from helpers import create_container, percentile

from conftest import patch_runtime
from devprompt_ai.runtime.events import EventBus, EventSink

pytestmark = [pytest.mark.e2e]


async def test_sl01_events_ordered_and_payload_intact(
    event_bus: EventBus,
    api_client: Any,
    modules: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SL-01：API 按 seq 升序返回，payload 字段无损。"""
    patch_runtime(monkeypatch, modules, event_bus)
    await event_bus.append("s1", "run.started", {"request_id": "req-1"}, run_id="run-1")
    await event_bus.append("s1", "thought", {"text": "先看按钮", "phase": "INIT"}, run_id="run-1")
    await event_bus.append(
        "s1",
        "action",
        {"title": "读取文件", "detail": "src/components.tsx", "status": "ok", "output": "ok"},
        run_id="run-1",
    )
    await event_bus.append("s1", "stop", {"status": "done", "state": "DONE"}, run_id="run-1")

    resp = await api_client.get("/api/v1/events", params={"session_id": "s1", "before": 1 << 30})
    body = resp.json()
    assert body["code"] == 0
    items = body["data"]
    assert [item["seq"] for item in items] == [1, 2, 3, 4]
    assert [item["type"] for item in items] == ["run.started", "thought", "action", "stop"]
    assert items[1]["data"]["text"] == "先看按钮"
    assert items[2]["data"]["title"] == "读取文件"


async def test_sl02_pagination_has_no_gap_or_duplicate(event_bus: EventBus) -> None:
    """SL-02：2000 条事件按 before 游标翻页，无重复无缺口。"""
    for index in range(2000):
        await event_bus.append("s2", "thought", {"index": index})

    seen: list[int] = []
    before = 1 << 30
    while True:
        page = await event_bus.history_before("s2", before, limit=173)
        if not page:
            break
        assert [event.seq for event in page] == sorted(event.seq for event in page)
        seen = [event.seq for event in page] + seen
        before = page[0].seq
        if before <= 1:
            break
    assert seen == list(range(1, 2001))


async def test_sl03_session_isolation(event_bus: EventBus) -> None:
    """SL-03：A/B 会话交错写入，各自只看到自己的事件。"""
    for index in range(5):
        await event_bus.append("a", "thought", {"index": index})
        await event_bus.append("b", "action", {"index": index})

    events_a = await event_bus.replay("a", 0)
    events_b = await event_bus.replay("b", 0)
    assert [event.seq for event in events_a] == [1, 2, 3, 4, 5]
    assert [event.seq for event in events_b] == [1, 2, 3, 4, 5]
    assert {event.type for event in events_a} == {"thought"}
    assert {event.type for event in events_b} == {"action"}


async def test_sl04_write_failure_is_not_silent(event_bus: EventBus) -> None:
    """SL-04：事件存储失败必须抛给调用方，不得静默丢数据。"""

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    event_bus._store.append = _boom  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(OSError, match="disk full"):
        await event_bus.append("s1", "thought", {"text": "x"})


async def test_sl05_live_follow_receives_in_order(event_bus: EventBus) -> None:
    """SL-05：先订阅后写入，订阅端按 seq 顺序收到；断开后订阅清理。"""
    queue: asyncio.Queue[Any] = event_bus.subscribe("s5")
    task = asyncio.create_task(queue.get())
    await event_bus.append("s5", "thought", {"text": "a"})
    event = await asyncio.wait_for(task, timeout=1)
    assert event.seq == 1
    assert event.payload["text"] == "a"
    event_bus.unsubscribe("s5", queue)
    assert "s5" not in event_bus._subs  # noqa: SLF001


async def test_sl06_long_session_query_within_budget(event_bus: EventBus) -> None:
    """SL-06：5000 条事件的分页查询 P95 ≤500ms。"""
    for index in range(5000):
        await event_bus.append("s6", "thought", {"index": index})

    timings: list[float] = []
    before = 1 << 30
    for _ in range(10):
        started = time.perf_counter()
        page = await event_bus.history_before("s6", before, limit=200)
        timings.append((time.perf_counter() - started) * 1000)
        assert len(page) == 200
        before = page[0].seq
    assert percentile(timings, 95) <= 500, timings


async def test_sl07_runs_path_emits_full_event_stream(stack: Any, event_bus: EventBus) -> None:
    """SL-07：经 EventSink 的真实业务链路产出 run.started/thought/action/snapshot/stop。"""
    container = await create_container(stack.sessions)
    session_id = container.session_id
    await event_bus.append(session_id, "run.started", {"request_id": "req-7"}, run_id="run-7")
    sink = EventSink(event_bus, session_id, "run-7")
    snapshot = await stack.service.optimize(
        "local",
        "eval/recall/mock-react-admin",
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-7",
        progress=sink,
        session_id=session_id,
    )
    await event_bus.append(
        session_id,
        "snapshot",
        {"status": snapshot.status, "state": snapshot.state, "session_id": snapshot.session_id},
        run_id="run-7",
    )
    await event_bus.append(
        session_id,
        "stop",
        {"status": snapshot.status, "state": snapshot.state},
        run_id="run-7",
    )

    events = await event_bus.replay(session_id, 0)
    types = [event.type for event in events]
    assert types[0] == "run.started"
    assert "thought" in types
    assert "action" in types
    assert types[-1] == "stop"
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert events[0].payload["request_id"] == "req-7"
