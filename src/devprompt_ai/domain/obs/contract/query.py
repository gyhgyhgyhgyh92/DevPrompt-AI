"""Trace/Metrics/Replay 的标准查询与输出模型（纯数据）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from devprompt_ai.domain.obs.contract.version import (
    METRICS_SCHEMA_VERSION,
    REPLAY_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class TraceQuery:
    session_id: str = ""
    trace_id: str = ""
    kind: str = ""
    from_ts: str = ""
    to_ts: str = ""
    cursor: int = 0
    limit: int = 200


@dataclass(frozen=True, slots=True)
class AggregateQuery:
    session_id: str = ""
    trace_id: str = ""
    from_ts: str = ""
    to_ts: str = ""
    group_by: Literal["kind", "name", "model", "turn", "status"] = "kind"
    bucket: Literal["none", "minute", "hour", "day"] = "none"
    percentiles: tuple[int, ...] = (50, 95, 99)
    limit: int = 500


@dataclass(frozen=True, slots=True)
class MetricPoint:
    bucket: str
    count: int
    failed: int
    avg_ms: float
    p50_ms: int | None
    p95_ms: int | None
    p99_ms: int | None
    tokens: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "count": self.count,
            "failed": self.failed,
            "avg_ms": round(self.avg_ms, 2),
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "tokens": self.tokens,
        }


@dataclass(frozen=True, slots=True)
class MetricSeries:
    dimension: str
    key: str
    points: tuple[MetricPoint, ...]
    schema_version: int = METRICS_SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "key": self.key,
            "points": [point.to_payload() for point in self.points],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AlertDraft:
    rule_id: str
    severity: str
    scope_kind: str
    scope_key: str
    metric: str
    observed: float
    threshold: float
    message: str


@dataclass(frozen=True, slots=True)
class AlertRecord:
    alert_id: str
    rule_id: str
    severity: str
    status: str
    scope_kind: str
    scope_key: str
    metric: str
    observed: float
    threshold: float
    message: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: str
    cooldown_until: str
    schema_version: int = METRICS_SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "scope_kind": self.scope_kind,
            "scope_key": self.scope_key,
            "metric": self.metric,
            "observed": self.observed,
            "threshold": self.threshold,
            "message": self.message,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "resolved_at": self.resolved_at,
            "cooldown_until": self.cooldown_until,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ReplayNodeResult:
    seq: int
    kind: str
    name: str
    match: bool
    expected: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "name": self.name,
            "match": self.match,
            "expected": self.expected,
            "actual": self.actual,
            "diff": self.diff,
        }


@dataclass(frozen=True, slots=True)
class ReplayRunRecord:
    run_id: str
    mode: str
    status: str
    left_trace_id: str
    right_trace_id: str
    matched_nodes: int
    mismatched_nodes: int
    missing_nodes: int
    result: dict[str, Any]
    error: dict[str, Any]
    created_at: str
    ended_at: str
    schema_version: int = REPLAY_SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "left_trace_id": self.left_trace_id,
            "right_trace_id": self.right_trace_id,
            "matched_nodes": self.matched_nodes,
            "mismatched_nodes": self.mismatched_nodes,
            "missing_nodes": self.missing_nodes,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[dict[str, Any], ...]
    has_more: bool
    next_cursor: int
    limit: int
