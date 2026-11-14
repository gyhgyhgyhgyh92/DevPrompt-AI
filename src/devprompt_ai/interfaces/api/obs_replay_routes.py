"""Replay 模块只读/任务 API（verify 与 compare）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.obs.contract.version import REPLAY_SCHEMA_VERSION
from devprompt_ai.interfaces.api.obs_common import obs_modules, request_id_of, require_enabled
from devprompt_ai.interfaces.api.schemas import ApiResponse

router = APIRouter(prefix="/api/v1/obs/replay", tags=["obs-replay"])


class ReplayCreateRequest(BaseModel):
    mode: Literal["verify", "compare"] = "verify"
    left_trace_id: str = Field(min_length=1)
    right_trace_id: str = ""


class ReplayCompareRequest(BaseModel):
    left_trace_id: str = Field(min_length=1)
    right_trace_id: str = Field(min_length=1)


class ReplayRunPayload(BaseModel):
    run: dict[str, Any]
    nodes: list[dict[str, Any]]
    schema_version: int = REPLAY_SCHEMA_VERSION


class ReplayComparePayload(BaseModel):
    nodes: list[dict[str, Any]]
    final: dict[str, Any]
    schema_version: int = REPLAY_SCHEMA_VERSION


@router.post("/runs", status_code=202, response_model=ApiResponse[ReplayRunPayload])
async def create_run(request: Request, body: ReplayCreateRequest) -> ApiResponse[ReplayRunPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.replay, "replay")
    try:
        record = await service.create(
            mode=body.mode,
            left_trace_id=body.left_trace_id,
            right_trace_id=body.right_trace_id,
        )
    except ValueError as exc:
        raise DevPromptError(str(exc), code=2001, context={}) from exc
    return ApiResponse(
        data=ReplayRunPayload(run=record.to_payload(), nodes=[]),
        request_id=request_id_of(request),
    )


@router.get("/runs/{run_id}", response_model=ApiResponse[ReplayRunPayload])
async def get_run(request: Request, run_id: str) -> ApiResponse[ReplayRunPayload]:
    modules = await obs_modules()
    service = require_enabled(modules.replay, "replay")
    record, nodes = await service.get(run_id)
    if record is None:
        raise DevPromptError("回放任务不存在", code=6003, context={"run_id": run_id})
    return ApiResponse(
        data=ReplayRunPayload(run=record.to_payload(), nodes=[node.to_payload() for node in nodes]),
        request_id=request_id_of(request),
    )


@router.post("/compare", response_model=ApiResponse[ReplayComparePayload])
async def compare(
    request: Request, body: ReplayCompareRequest
) -> ApiResponse[ReplayComparePayload]:
    modules = await obs_modules()
    service = require_enabled(modules.replay, "replay")
    try:
        nodes, final = await service.compare_now(body.left_trace_id, body.right_trace_id)
    except ValueError as exc:
        raise DevPromptError(str(exc), code=2001, context={}) from exc
    return ApiResponse(
        data=ReplayComparePayload(nodes=[node.to_payload() for node in nodes], final=final),
        request_id=request_id_of(request),
    )
