"""Trace 模块应用服务（独立启用/升级）。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.obs.contract.query import TraceQuery
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceSummary
from devprompt_ai.domain.obs.trace.tree import build_tree, flatten_preview
from devprompt_ai.memory.trace_store import SQLiteTraceStore


class TraceService:
    def __init__(self, store: SQLiteTraceStore, collector: Any, *, enabled: bool = True) -> None:
        self._store = store
        self._collector = collector
        self.enabled = enabled

    async def startup(self, retention_days: int) -> None:
        await self._store.init_schema()
        await self._store.cleanup_expired(retention_days)

    async def list_traces(self, session_id: str, *, limit: int = 200) -> list[TraceSummary]:
        return await self._store.list_traces(session_id, limit=limit)

    async def query_events(self, query: TraceQuery) -> tuple[list[dict[str, Any]], bool, int]:
        events, has_more, cursor = await self._store.query_events(query)
        return flatten_preview(events), has_more, cursor

    async def trace_tree(self, trace_id: str, *, full: bool = False) -> list[dict[str, Any]]:
        events = await self._store.list_trace_events(trace_id)
        return build_tree(events, full=full)

    async def get_event(self, event_id: str) -> TraceEvent | None:
        return await self._store.get_event(event_id)

    async def flush(self) -> None:
        await self._collector.flush_all()
