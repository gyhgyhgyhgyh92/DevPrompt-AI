"""Trace 模块只读 API（独立启用/升级）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from devprompt_ai.domain.obs.contract.query import TraceQuery
from devprompt_ai.domain.obs.contract.version import TRACE_SCHEMA_VERSION
from devprompt_ai.interfaces.api.obs_common import obs_modules, request_id_of, require_enabled
from devprompt_ai.interfaces.api.schemas import ApiResponse

router = APIRouter(prefix="/api/v1/obs/trace", tags=["obs-trace"])


class TraceListPayload(BaseModel):
    items: list[dict[str, Any]]
    schema_version: int = TRACE_SCHEMA_VERSION


class TraceEventsPayload(BaseModel):
    items: list[dict[str, Any]]
    has_more: bool
    next_cursor: int
    schema_version: int = TRACE_SCHEMA_VERSION


class TraceTreePayload(BaseModel):
    trace_id: str
    items: list[dict[str, Any]]
    schema_version: int = TRACE_SCHEMA_VERSION


class TraceEventPayload(BaseModel):
    event: dict[str, Any] | None = None
    schema_version: int = TRACE_SCHEMA_VERSION


@router.get("/sessions/{session_id}/traces", response_model=ApiResponse[TraceListPayload])
async def list_traces(
    request: Request, session_id: str, limit: Annotated[int, Query(ge=1, le=500)] = 200
) -> ApiResponse[TraceListPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.trace, "trace")
    items = [item.to_payload() for item in await service.list_traces(session_id, limit=limit)]
    return ApiResponse(data=TraceListPayload(items=items), request_id=request_id_of(request))


@router.get("/sessions/{session_id}/events", response_model=ApiResponse[TraceEventsPayload])
async def list_events(
    request: Request,
    session_id: str,
    kind: str = "",
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> ApiResponse[TraceEventsPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.trace, "trace")
    items, has_more, next_cursor = await service.query_events(
        TraceQuery(session_id=session_id, kind=kind, cursor=cursor, limit=limit)
    )
    return ApiResponse(
        data=TraceEventsPayload(items=items, has_more=has_more, next_cursor=next_cursor),
        request_id=request_id_of(request),
    )


@router.get("/traces/{trace_id}", response_model=ApiResponse[TraceTreePayload])
async def get_trace(
    request: Request, trace_id: str, full: bool = False
) -> ApiResponse[TraceTreePayload]:
    modules = await obs_modules()
    service = require_enabled(modules.trace, "trace")
    items = await service.trace_tree(trace_id, full=full)
    return ApiResponse(
        data=TraceTreePayload(trace_id=trace_id, items=items),
        request_id=request_id_of(request),
    )


@router.get("/events/{event_id}", response_model=ApiResponse[TraceEventPayload])
async def get_event(request: Request, event_id: str) -> ApiResponse[TraceEventPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.trace, "trace")
    event = await service.get_event(event_id)
    return ApiResponse(
        data=TraceEventPayload(event=event.to_payload(full=True) if event else None),
        request_id=request_id_of(request),
    )
