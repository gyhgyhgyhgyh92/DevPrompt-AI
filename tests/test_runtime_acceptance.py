"""验收测试（不依赖外网）：多端一致、重启补帧、长会话有界、写工串行。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from devprompt_ai.domain.agent.work_order import WorkOrder
from devprompt_ai.domain.context.micro import micro_compact
from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.runtime.coordinator import DelegationCoordinator
from devprompt_ai.runtime.events import EventBus, follow


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "accept.db")


async def _collect(bus: EventBus, session: str, since: int, *, expect: int) -> list[int]:
    seqs: list[int] = []
    async for event in follow(bus, session, since=since, heartbeat_s=5):
        if event.seq == 0:
            continue
        seqs.append(event.seq)
        if len(seqs) >= expect:
            break
    return seqs


async def test_two_devices_see_same_timeline_and_reconnect_resumes(tmp_path: Path) -> None:
    bus = EventBus(SQLiteEventStore(_db(tmp_path)))
    session = "s1"

    # 设备 A、B 同时订阅（先订阅后生产，模拟真实建连）
    task_a = asyncio.create_task(_collect(bus, session, 0, expect=3))
    task_b = asyncio.create_task(_collect(bus, session, 0, expect=3))
    await asyncio.sleep(0)

    for index in range(3):
        await bus.append(session, "thought", {"index": index})

    assert await asyncio.wait_for(task_a, timeout=1) == [1, 2, 3]
    assert await asyncio.wait_for(task_b, timeout=1) == [1, 2, 3], "两端看到同一时间线"

    # 设备 B 断线后继续生产；重开只补差
    await bus.append(session, "thought", {"index": 3})
    await bus.append(session, "action", {"title": "x"})

    assert await _collect(bus, session, 3, expect=2) == [4, 5], "重连从 since=3 补齐"


async def test_restart_replays_from_disk(tmp_path: Path) -> None:
    db = _db(tmp_path)
    first = EventBus(SQLiteEventStore(db))
    await first.append("s1", "thought", {"text": "before-restart"})

    # 模拟进程重启：新建 store/bus，历史仍可读
    second = EventBus(SQLiteEventStore(db))
    events = await second.replay("s1", 0)

    assert [event.seq for event in events] == [1]
    assert events[0].payload["text"] == "before-restart"


def test_long_session_compaction_stays_bounded() -> None:
    """100 轮持续追加 + micro 压缩：文本长度必须收敛，不得线性膨胀。"""
    text = ""
    for index in range(100):
        text = micro_compact(text + f"第 {index} 轮的工具输出" + "x" * 500, preview_chars=1200)

    assert len(text) <= 1400, "每轮截断后长度有界"
    assert "microcompacted" in text


async def test_write_orders_are_serialized(tmp_path: Path) -> None:
    coordinator = DelegationCoordinator(write_cap=1)
    active = 0
    peak = 0

    async def worker(_order: WorkOrder) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    orders = [
        WorkOrder(f"w{i}", "t1", "patcher", f"改文件{i}", scope_files=(f"src/f{i}.py",))
        for i in range(3)
    ]
    await asyncio.gather(*(coordinator.run(order, worker) for order in orders))

    assert peak == 1, "写工池容量为 1，必须串行"
    assert coordinator.inflight == frozenset()
