"""三模块共享端口（Protocol，零实现依赖，MUST-06）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from devprompt_ai.domain.obs.contract.query import (
    AggregateQuery,
    AlertDraft,
    AlertRecord,
    MetricSeries,
    ReplayNodeResult,
    ReplayRunRecord,
    TraceQuery,
)
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceSummary


@runtime_checkable
class TraceStore(Protocol):
    async def append_events(self, events: Sequence[TraceEvent]) -> None: ...

    async def list_traces(self, session_id: str, *, limit: int = 200) -> list[TraceSummary]: ...

    async def query_events(self, query: TraceQuery) -> tuple[list[TraceEvent], bool, int]: ...

    async def list_trace_events(self, trace_id: str) -> list[TraceEvent]: ...

    async def get_event(self, event_id: str) -> TraceEvent | None: ...

    async def aggregate(self, query: AggregateQuery) -> list[MetricSeries]: ...

    async def last_seq(self, trace_id: str) -> int: ...

    async def cleanup_expired(self, retention_days: int) -> int: ...


@runtime_checkable
class TraceReader(Protocol):
    async def list_traces(self, session_id: str, *, limit: int = 200) -> list[TraceSummary]: ...

    async def query_events(self, query: TraceQuery) -> tuple[list[TraceEvent], bool, int]: ...

    async def list_trace_events(self, trace_id: str) -> list[TraceEvent]: ...

    async def get_event(self, event_id: str) -> TraceEvent | None: ...

    async def aggregate(self, query: AggregateQuery) -> list[MetricSeries]: ...


@runtime_checkable
class TraceCollector(Protocol):
    async def start_turn(self, **meta: Any) -> None: ...

    async def record(self, **event: Any) -> None: ...

    async def end_turn(self, **meta: Any) -> None: ...

    async def flush(self) -> None: ...


@runtime_checkable
class TraceListener(Protocol):
    async def on_trace_completed(self, trace_id: str, session_id: str) -> None: ...


@runtime_checkable
class AlertStore(Protocol):
    async def sync_alerts(
        self, drafts: Sequence[AlertDraft], *, scope_kind: str, scope_key: str
    ) -> None: ...

    async def list_alerts(
        self, *, status: str = "", limit: int = 50, offset: int = 0
    ) -> list[AlertRecord]: ...


@runtime_checkable
class ReplayStore(Protocol):
    async def create_run(self, record: ReplayRunRecord) -> None: ...

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        matched: int,
        mismatched: int,
        missing: int,
        result: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> None: ...

    async def get_run(self, run_id: str) -> ReplayRunRecord | None: ...

    async def list_nodes(self, run_id: str) -> list[ReplayNodeResult]: ...


@runtime_checkable
class ReplayExecutionPort(Protocol):
    async def execute(
        self,
        trace_events: Sequence[TraceEvent],
        *,
        collector: TraceCollector,
    ) -> tuple[dict[str, Any], list[ReplayNodeResult]]: ...
