"""指标纯聚合（2026-11-12）：把 Trace 行聚合成标准 MetricSeries。

本模块不读数据库、不做判定；SQL 由 ``memory/trace_store.py`` 执行。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final

from devprompt_ai.domain.obs.contract.query import MetricPoint, MetricSeries


@dataclass(frozen=True, slots=True)
class TraceRow:
    """聚合输入行（store 从 trace_events 投影）。"""

    kind: str
    name: str
    status: str
    turn_index: int
    model_id: str
    duration_ms: int
    tokens: int
    started_at: str


_DIMENSION_VALUE: Final[dict[str, str]] = {
    "kind": "kind",
    "name": "name",
    "model": "model_id",
    "turn": "turn_index",
    "status": "status",
}


def percentile(values: list[int], pct: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight)


def _bucket_of(ts: str, bucket: str) -> str:
    """SQLite/ISO 时间 → 时间桶；无法解析时按原文分组（不猜时间）。"""
    if len(ts) < 16:
        return ts
    if bucket == "minute":
        return ts[:16]
    if bucket == "hour":
        return ts[:13]
    if bucket == "day":
        return ts[:10]
    return ""


def build_series(
    rows: list[TraceRow],
    *,
    dimension: str,
    bucket: str,
    percentiles: tuple[int, ...],
    limit: int = 500,
) -> list[MetricSeries]:
    """按维度与时间桶聚合；同一 (dimension,key,bucket) 合并。"""
    if dimension not in _DIMENSION_VALUE:
        raise ValueError(f"不支持的聚合维度：{dimension}")
    groups: dict[tuple[str, str], list[TraceRow]] = defaultdict(list)
    for row in rows:
        key = str(getattr(row, _DIMENSION_VALUE[dimension]))
        groups[(key, _bucket_of(row.started_at, bucket))].append(row)

    ordered_keys = sorted({key for key, _ in groups})[:limit]
    series: list[MetricSeries] = []
    for key in ordered_keys:
        points: list[MetricPoint] = []
        for (group_key, time_bucket), items in sorted(groups.items()):
            if group_key != key:
                continue
            durations = [item.duration_ms for item in items if item.duration_ms >= 0]
            failed = sum(1 for item in items if item.status == "failed")
            values = {pct: percentile(durations, pct) for pct in percentiles}
            points.append(
                MetricPoint(
                    bucket=time_bucket,
                    count=len(items),
                    failed=failed,
                    avg_ms=(sum(durations) / len(durations)) if durations else 0.0,
                    p50_ms=values.get(50),
                    p95_ms=values.get(95),
                    p99_ms=values.get(99),
                    tokens=sum(item.tokens for item in items),
                )
            )
        series.append(MetricSeries(dimension=dimension, key=key, points=tuple(points)))
    return series


def rows_from_dicts(items: list[dict[str, Any]]) -> list[TraceRow]:
    return [
        TraceRow(
            kind=str(item.get("kind", "")),
            name=str(item.get("name", "")),
            status=str(item.get("status", "")),
            turn_index=int(item.get("turn_index", 0) or 0),
            model_id=str(item.get("model_id", "") or ""),
            duration_ms=int(item.get("duration_ms", 0) or 0),
            tokens=int(item.get("tokens", 0) or 0),
            started_at=str(item.get("started_at", "") or ""),
        )
        for item in items
    ]
