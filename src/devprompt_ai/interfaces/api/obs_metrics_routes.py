"""Metrics 模块只读 API（聚合、告警历史、阈值配置）。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from devprompt_ai.domain.obs.contract.query import AggregateQuery
from devprompt_ai.domain.obs.contract.version import METRICS_SCHEMA_VERSION
from devprompt_ai.interfaces.api.obs_common import obs_modules, request_id_of, require_enabled
from devprompt_ai.interfaces.api.schemas import ApiResponse

router = APIRouter(prefix="/api/v1/obs/metrics", tags=["obs-metrics"])


class MetricSummaryPayload(BaseModel):
    items: list[dict[str, Any]]
    schema_version: int = METRICS_SCHEMA_VERSION


class AlertListPayload(BaseModel):
    items: list[dict[str, Any]]
    limit: int
    offset: int
    schema_version: int = METRICS_SCHEMA_VERSION


class MetricsConfigPayload(BaseModel):
    config: dict[str, Any]
    schema_version: int = METRICS_SCHEMA_VERSION


@router.get("/summary", response_model=ApiResponse[MetricSummaryPayload])
async def summary(
    request: Request,
    session_id: str = "",
    trace_id: str = "",
    from_ts: str = "",
    to_ts: str = "",
    group_by: Literal["kind", "name", "model", "turn", "status"] = "kind",
    bucket: Literal["none", "minute", "hour", "day"] = "none",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> ApiResponse[MetricSummaryPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.metrics, "metrics")
    series = await service.summary(
        AggregateQuery(
            session_id=session_id,
            trace_id=trace_id,
            from_ts=from_ts,
            to_ts=to_ts,
            group_by=group_by,
            bucket=bucket,
            limit=limit,
        )
    )
    return ApiResponse(
        data=MetricSummaryPayload(items=[item.to_payload() for item in series]),
        request_id=request_id_of(request),
    )


@router.get("/alerts", response_model=ApiResponse[AlertListPayload])
async def alerts(
    request: Request,
    status: Literal["", "active", "resolved"] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[AlertListPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.metrics, "metrics")
    items = await service.alerts(status=status, limit=limit, offset=offset)
    return ApiResponse(
        data=AlertListPayload(
            items=[item.to_payload() for item in items], limit=limit, offset=offset
        ),
        request_id=request_id_of(request),
    )


@router.get("/config", response_model=ApiResponse[MetricsConfigPayload])
async def get_config(request: Request) -> ApiResponse[MetricsConfigPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.metrics, "metrics")
    return ApiResponse(
        data=MetricsConfigPayload(config=service.config_payload()),
        request_id=request_id_of(request),
    )
