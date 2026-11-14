"""运行时层测试：事件 seq/重放、会话并发闸、运行生命周期与解耦。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.progress import ProgressEvent
from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.memory.run_store import SQLiteRunStore
from devprompt_ai.runtime.events import EventBus, EventSink, follow
from devprompt_ai.runtime.runs import RunManager
from devprompt_ai.runtime.sessions import SessionPool
from devprompt_ai.runtime.streams import sse_frame
from devprompt_ai.service import FlowSnapshot, ForgeService


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "runtime.db")


class _FakeService:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def optimize(self, *args: Any, **kwargs: Any) -> FlowSnapshot:
        self.calls.append(kwargs)
        sink = kwargs.get("progress")
        if sink is not None:
            await sink.emit(ProgressEvent(text="开始", phase="INIT"))
        if self.delay:
            await asyncio.sleep(self.delay)
        return FlowSnapshot(session_id="s1", status="done", state="DONE")


async def _wait_done(store: SQLiteRunStore, run_id: str, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        record = await store.get(run_id)
        if record is not None and record.is_terminal:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("运行未在超时内结束")


async def test_event_bus_appends_and_replays(tmp_path: Path) -> None:
    store = SQLiteEventStore(_db(tmp_path))
    bus = EventBus(store)

    await bus.append("s1", "thought", {"text": "a"})
    await bus.append("s1", "action", {"title": "b"})

    assert [e.seq for e in await bus.replay("s1", 1)] == [2]
    assert [e.seq for e in await bus.history_before("s1", 2, limit=1)] == [1]


async def test_event_sink_translates_progress(tmp_path: Path) -> None:
    bus = EventBus(SQLiteEventStore(_db(tmp_path)))
    sink = EventSink(bus, "s1", "r1")

    await sink.emit(ProgressEvent(text="hi", phase="INIT"))
    await sink.emit(ProgressEvent(action=None, text=""))

    events = await bus.replay("s1", 0)
    assert [e.type for e in events] == ["thought", "thought"]
    assert events[0].payload["text"] == "hi"


async def test_session_pool_rejects_concurrent_run(tmp_path: Path) -> None:
    pool = SessionPool()
    assert pool.try_acquire("s1", "r1") is True
    task = asyncio.create_task(asyncio.sleep(1))
    pool.attach_task("s1", task)

    assert pool.active_run("s1") == "r1"
    assert pool.try_acquire("s1", "r2") is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_manager_decouples_execution_from_caller(tmp_path: Path) -> None:
    db = _db(tmp_path)
    runs = SQLiteRunStore(db)
    bus = EventBus(SQLiteEventStore(db))
    pool = SessionPool()
    service = _FakeService()
    manager = RunManager(
        service=cast(ForgeService, service),
        bus=bus,
        runs=runs,
        pool=pool,
        serialize=lambda snapshot: {"status": snapshot.status, "state": snapshot.state},
    )

    record = await manager.start(session_id="s1", project="p", sentence="改一下", request_id="req")
    await _wait_done(runs, record.run_id)

    finished = await runs.get(record.run_id)
    assert finished is not None
    assert finished.status == "done"
    events = await bus.replay("s1", 0)
    assert [e.type for e in events] == ["run.started", "thought", "snapshot", "stop"]
    assert service.calls[-1]["create_session"] is True, "/runs 必须允许创建前端新会话"
    assert pool.active_run("s1") is None


async def test_run_manager_rejects_second_run_on_same_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    runs = SQLiteRunStore(db)
    bus = EventBus(SQLiteEventStore(db))
    pool = SessionPool()
    manager = RunManager(
        service=cast(ForgeService, _FakeService(delay=0.2)),
        bus=bus,
        runs=runs,
        pool=pool,
        serialize=lambda snapshot: {"status": snapshot.status},
    )

    first = await manager.start(session_id="s1", project="p", sentence="a", request_id="r1")
    with pytest.raises(StateError):
        await manager.start(session_id="s1", project="p", sentence="b", request_id="r2")

    await _wait_done(runs, first.run_id)


async def test_run_manager_cancel_marks_aborted(tmp_path: Path) -> None:
    db = _db(tmp_path)
    runs = SQLiteRunStore(db)
    manager = RunManager(
        service=cast(ForgeService, _FakeService(delay=5)),
        bus=EventBus(SQLiteEventStore(db)),
        runs=runs,
        pool=SessionPool(),
        serialize=lambda snapshot: {"status": snapshot.status},
    )

    record = await manager.start(session_id="s1", project="p", sentence="a", request_id="r")
    assert await manager.cancel(record.run_id) is True
    await _wait_done(runs, record.run_id)

    finished = await runs.get(record.run_id)
    assert finished is not None
    assert finished.status == "aborted"


async def test_follow_replays_then_finishes_on_stop(tmp_path: Path) -> None:
    bus = EventBus(SQLiteEventStore(_db(tmp_path)))
    await bus.append("s1", "thought", {"text": "old"})
    await bus.append("s1", "stop", {"status": "done"})

    seen = [event.type async for event in follow(bus, "s1", since=0, heartbeat_s=0.05)]

    assert seen == ["thought", "stop"]


async def test_sse_frame_carries_seq_and_ping() -> None:
    from devprompt_ai.domain.events import RunEvent

    frame = sse_frame(RunEvent(session_id="s1", seq=3, type="thought", payload={"text": "x"}))
    assert frame.startswith("id: 3\n")
    assert '"seq": 3' in frame

    ping = sse_frame(RunEvent(session_id="s1", seq=0, type="ping"))
    assert ping == ": ping\n\n"
