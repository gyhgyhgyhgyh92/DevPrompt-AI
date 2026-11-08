"""事件总线：先落库、再扇出；重连只补差。

设计要点（对齐天枢 server/protocol.ts）：
- ``seq`` 由存储层在事务内分配，多端看到同一条时间线；
- 慢订阅者丢帧而不是阻塞执行——前端凭 ``since`` 补回；
- 合成快照 ``seq=0`` 每次建连重发，不落库，天然幂等。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from devprompt_ai.domain.events import RunEvent
from devprompt_ai.domain.progress import ProgressEvent, ProgressSink
from devprompt_ai.memory.event_store import SQLiteEventStore

#: 单个订阅者的队列上限：满了就丢帧，执行体绝不因慢客户端阻塞。
_SUBSCRIBER_QUEUE_SIZE = 2048


class EventBus:
    def __init__(self, store: SQLiteEventStore) -> None:
        self._store = store
        self._subs: dict[str, set[asyncio.Queue[RunEvent]]] = {}

    async def append(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        run_id: str = "",
    ) -> RunEvent:
        event = await self._store.append(session_id, event_type, payload, run_id=run_id)
        self._fanout(event)
        return event

    def _fanout(self, event: RunEvent) -> None:
        for queue in tuple(self._subs.get(event.session_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    def subscribe(self, session_id: str) -> asyncio.Queue[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        self._subs.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[RunEvent]) -> None:
        subs = self._subs.get(session_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subs.pop(session_id, None)

    async def replay(self, session_id: str, since: int, *, limit: int = 500) -> list[RunEvent]:
        return await self._store.since(session_id, since, limit=limit)

    async def history_before(
        self, session_id: str, seq: int, *, limit: int = 500
    ) -> list[RunEvent]:
        return await self._store.before(session_id, seq, limit=limit)

    async def last_seq(self, session_id: str) -> int:
        return await self._store.last_seq(session_id)

    @staticmethod
    def synthetic_snapshot(session_id: str, payload: dict[str, Any]) -> RunEvent:
        """建连快照：seq=0、不落库；客户端按类型幂等 upsert。"""
        return RunEvent(session_id=session_id, seq=0, type="snapshot", payload=payload)


class EventSink(ProgressSink):
    """把 ``ProgressEvent`` 翻译成会话事件的出口。

    service 只认 ``ProgressSink``，本适配器让它有落库与多端扇出能力。
    """

    def __init__(self, bus: EventBus, session_id: str, run_id: str) -> None:
        self._bus = bus
        self._session_id = session_id
        self._run_id = run_id

    async def emit(self, event: ProgressEvent) -> None:
        if event.action is None:
            await self._bus.append(
                self._session_id,
                "thought",
                {"text": event.text, "phase": event.phase},
                run_id=self._run_id,
            )
            return
        action = event.action
        await self._bus.append(
            self._session_id,
            "action",
            {
                "phase": event.phase,
                "title": action.title,
                "detail": action.detail,
                "scope": action.scope,
                "output": action.output,
                "status": action.status,
                "duration_ms": action.duration_ms,
            },
            run_id=self._run_id,
        )


async def follow(
    bus: EventBus,
    session_id: str,
    *,
    since: int,
    snapshot: RunEvent | None = None,
    heartbeat_s: float = 15.0,
    stop_on: frozenset[str] = frozenset({"stop", "error"}),
) -> AsyncIterator[RunEvent]:
    """先回放 ``since`` 之后的历史，再跟随实时事件。

    先订阅后回放：避免「回放结束到订阅建立」之间的事件丢失；重复的 seq 由 ``last`` 跳过。
    """
    queue = bus.subscribe(session_id)
    last = since
    try:
        if snapshot is not None:
            yield snapshot
        for event in await bus.replay(session_id, since):
            last = max(last, event.seq)
            yield event
            if event.type in stop_on:
                return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_s)
            except TimeoutError:
                yield RunEvent(session_id=session_id, seq=0, type="ping", payload={})
                continue
            if event.seq <= last:
                continue
            last = event.seq
            yield event
            if event.type in stop_on:
                return
    finally:
        bus.unsubscribe(session_id, queue)
