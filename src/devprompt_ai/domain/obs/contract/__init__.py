"""共享契约包（三模块唯一允许的共同依赖）。"""

from __future__ import annotations

from devprompt_ai.domain.obs.contract.ports import (
    AlertStore,
    ReplayExecutionPort,
    ReplayStore,
    TraceCollector,
    TraceListener,
    TraceReader,
    TraceStore,
)
from devprompt_ai.domain.obs.contract.query import (
    AggregateQuery,
    AlertDraft,
    AlertRecord,
    MetricPoint,
    MetricSeries,
    Page,
    ReplayNodeResult,
    ReplayRunRecord,
    TraceQuery,
)
from devprompt_ai.domain.obs.contract.trace import (
    TraceEvent,
    TraceKind,
    TraceStatus,
    TraceSummary,
    canonical_json,
    hash_key,
    mask_secrets,
    preview,
)
from devprompt_ai.domain.obs.contract.version import (
    METRICS_SCHEMA_VERSION,
    REPLAY_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
)

__all__ = [
    "AlertDraft",
    "AlertRecord",
    "AlertStore",
    "AggregateQuery",
    "MetricPoint",
    "MetricSeries",
    "METRICS_SCHEMA_VERSION",
    "Page",
    "REPLAY_SCHEMA_VERSION",
    "ReplayExecutionPort",
    "ReplayNodeResult",
    "ReplayRunRecord",
    "ReplayStore",
    "TRACE_SCHEMA_VERSION",
    "TraceCollector",
    "TraceEvent",
    "TraceKind",
    "TraceListener",
    "TraceQuery",
    "TraceReader",
    "TraceStatus",
    "TraceStore",
    "TraceSummary",
    "canonical_json",
    "hash_key",
    "mask_secrets",
    "preview",
]
