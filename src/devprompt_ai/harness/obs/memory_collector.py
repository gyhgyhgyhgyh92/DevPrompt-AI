"""内存 Trace 采集器（Replay 自比对用，不落库）。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.obs.contract.trace import TraceEvent
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl


class _ListStore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def append_events(self, events: list[TraceEvent]) -> None:
        self.events.extend(events)


class MemoryTraceCollector(TraceCollectorImpl):
    def __init__(self) -> None:
        self._list_store = _ListStore()
        super().__init__(self._list_store, enabled=True)  # type: ignore[arg-type]

    @property
    def events(self) -> list[TraceEvent]:
        return self._list_store.events

    def add_listener(self, listener: Any) -> None:
        return None
