"""Web 路由薄壳（MUST-10）：只做参数收拢 → 调 service → 渲染，零业务逻辑。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import StateError
from devprompt_ai.interfaces.api import health
from devprompt_ai.interfaces.api.schemas import (
    ApiResponse,
    FeedbackRequest,
    FlowSnapshotResponse,
    FollowupRequest,
    OptimizeRequest,
    ScanResponse,
    UnknownItemPayload,
)
from devprompt_ai.service import FlowSnapshot, ForgeService, build_default

router = APIRouter(prefix="/api/v1")

_USER_ID = "local"
_NOT_IMPLEMENTED_CODE = 9004

_service: ForgeService | None = None


async def get_service() -> ForgeService:
    """懒加载单例：复用 service.build_default 组装（MUST-10 单一业务来源）。"""
    global _service
    if _service is None:
        cfg = AppConfig()
        cfg.validate()
        _service = await build_default(cfg)
    return _service


def _ok(data: Any, request_id: str) -> ApiResponse:
    return ApiResponse(code=0, message="ok", data=data, request_id=request_id)


def _snapshot_payload(snapshot: FlowSnapshot) -> FlowSnapshotResponse:
    """快照渲染（dataclass → 契约模型；VariantDraft 为 pydantic 模型需 model_dump）。"""
    return FlowSnapshotResponse(
        session_id=snapshot.session_id,
        status=snapshot.status,
        state=snapshot.state,
        questions=[
            UnknownItemPayload(key=q.key, reason=q.reason, best_guess=q.best_guess, ask=q.ask)
            for q in snapshot.questions
        ],
        cleared=snapshot.cleared,
        variant=snapshot.variant.model_dump() if snapshot.variant is not None else None,
        message=snapshot.message,
    )


def _not_implemented(message: str) -> JSONResponse:
    body = ApiResponse(code=_NOT_IMPLEMENTED_CODE, message=message, request_id=uuid.uuid4().hex)
    return JSONResponse(status_code=501, content=body.model_dump())


@router.get("/health")
async def get_health() -> ApiResponse:
    request_id = uuid.uuid4().hex
    report = await health.run_checks(AppConfig())
    return _ok(report, request_id)


@router.post(
    "/optimize",
    description="有副作用端点：禁止客户端自动重试（MUST-15，重复提交将产生重复流程）。",
)
async def post_optimize(req: OptimizeRequest) -> ApiResponse:
    request_id = uuid.uuid4().hex
    svc = await get_service()
    snapshot = await svc.optimize(_USER_ID, req.project, req.sentence, request_id=request_id)
    return _ok(_snapshot_payload(snapshot), request_id)


@router.get("/progress/{flow_id}")
async def get_progress(flow_id: str) -> StreamingResponse:
    """SSE 进度流：1s 轮询快照；DONE/ABORTED/ASKING/护栏推送后关闭；客户端断开即停。"""
    request_id = uuid.uuid4().hex

    async def _events() -> AsyncIterator[str]:
        while True:
            try:
                svc = await get_service()
                snapshot = await svc.resume(_USER_ID, flow_id, request_id=request_id)
            except StateError as exc:
                # ABORTED 不在 resume 允许态集内，经异常上下文识别后以扩展 status 收尾
                if exc.context.get("state") == "ABORTED":
                    aborted = FlowSnapshotResponse(
                        session_id=flow_id,
                        status="aborted",
                        state="ABORTED",
                        message="流程已中止",
                    )
                    yield f"data: {aborted.model_dump_json()}\n\n"
                else:
                    err = ApiResponse(code=exc.code, message=str(exc), request_id=request_id)
                    yield f"data: {err.model_dump_json()}\n\n"
                return
            yield f"data: {_snapshot_payload(snapshot).model_dump_json()}\n\n"
            if snapshot.state in ("DONE", "ABORTED") or snapshot.status in ("ask", "guardrail"):
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.post("/followup/{flow_id}")
async def post_followup(flow_id: str, req: FollowupRequest) -> ApiResponse:
    """三模式分发（互斥由契约校验保证）：批量答复 / 逃生 / 软护栏裁决（MUST-26）。"""
    request_id = uuid.uuid4().hex
    svc = await get_service()
    if req.escape:
        snapshot = await svc.escape(_USER_ID, flow_id, request_id=request_id)
    elif req.guardrail_action is not None:
        snapshot = await svc.guardrail_confirm(
            _USER_ID, flow_id, req.guardrail_action == "continue", request_id=request_id
        )
    else:
        snapshot = await svc.ask_followup(
            _USER_ID, flow_id, req.answers or {}, request_id=request_id
        )
    return _ok(_snapshot_payload(snapshot), request_id)


@router.get("/result/{flow_id}")
async def get_result(flow_id: str) -> ApiResponse:
    request_id = uuid.uuid4().hex
    svc = await get_service()
    snapshot = await svc.resume(_USER_ID, flow_id, request_id=request_id)
    return _ok(_snapshot_payload(snapshot), request_id)


@router.post("/feedback")
async def post_feedback(req: FeedbackRequest) -> ApiResponse:
    request_id = uuid.uuid4().hex
    svc = await get_service()
    await svc.feedback(_USER_ID, req.session_id, req.action, request_id=request_id)
    return _ok(None, request_id)


@router.get("/preference")
async def get_preference() -> ApiResponse:
    request_id = uuid.uuid4().hex
    svc = await get_service()
    pref = await svc.get_preference(_USER_ID)
    return _ok(pref, request_id)


@router.put("/preference")
async def put_preference() -> JSONResponse:
    """阶段五（L3）前不提供偏好写入——薄壳不造假数据。"""
    return _not_implemented("偏好写入将在阶段五(L3)接入")


@router.get("/history")
async def get_history() -> JSONResponse:
    """阶段五（L3）前不提供历史列表——session store 无 list 能力。"""
    return _not_implemented("历史列表将在阶段五(L3)接入")


@router.get("/project/scan")
async def get_project_scan(project: str) -> ApiResponse:
    request_id = uuid.uuid4().hex
    svc = await get_service()
    stats = await svc.scan_project(project)
    return _ok(ScanResponse(**stats), request_id)
