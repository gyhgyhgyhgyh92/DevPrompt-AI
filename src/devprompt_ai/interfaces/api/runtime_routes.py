"""运行时协议：先起 run，再订阅会话事件流。

与旧 `/optimize/stream` 的差别（BREAKING）：
- 执行的生死不再绑定连接：关掉所有前端，run 继续跑完；
- 事件按 `seq` 落库，`?since=N` 只补差；
- 建连先收 `seq=0` 合成快照（幂等 upsert），不需要前端猜自己缺了什么。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale
from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.interfaces.api.routes import _USER_ID, _snapshot_payload, get_service
from devprompt_ai.interfaces.api.schemas import (
    ApiResponse,
    ArtifactResponse,
    SessionModelResponse,
    validate_images,
)
from devprompt_ai.runtime.artifacts import read_tool_artifact
from devprompt_ai.runtime.bootstrap import RuntimeBundle, get_runtime
from devprompt_ai.runtime.events import EventBus, follow
from devprompt_ai.runtime.streams import sse_frame
from devprompt_ai.service import FlowSnapshot

router = APIRouter(prefix="/api/v1", tags=["runtime"])


class StartRunRequest(BaseModel):
    """启动一次运行。``session_id`` 由前端生成，便于立刻订阅。"""

    session_id: str = Field(min_length=1, max_length=128)
    project: str = ""
    sentence: str = ""
    base_turn_id: str = ""
    locale: str = "zh-CN"
    #: 领域覆盖（2026-11-14 领域包）：None=自动路由；白名单与 KNOWN_DOMAIN_IDS 同步
    domain: (
        Literal[
            "code",
            "work",
            "life",
            "creative",
            "learning",
            "data",
            "marketing",
            "translation",
            "legal",
            "medical",
            "finance",
            "game",
            "visual",
            "av",
            "operations",
        ]
        | None
    ) = None
    #: 视觉生成风格（2026-11-14 多模态）：仅 domain="visual" 时生效
    style: (
        Literal[
            "general",
            "photography",
            "creative",
            "chinese-model",
            "json-structured",
            "video",
        ]
        | None
    ) = None
    #: 图生图参考图（base64 data URL）：仅 domain="visual" 接受，校验规则同 /optimize
    images: list[str] | None = None

    @model_validator(mode="after")
    def _validate_images(self) -> StartRunRequest:
        validate_images(self.images, self.domain)
        return self


class InterventionAnswerRequest(BaseModel):
    """审批/提问的应答；``decision`` 必填，缺字段由 422 拒绝（不默认批准）。"""

    decision: Literal["approve", "deny", "answer"]
    answer: str = ""


class SessionModelRequest(BaseModel):
    """F10 会话级模型切换：``model_id`` 为注册表条目 id；空串 = 清除覆盖。"""

    model_id: str = Field(default="", max_length=200)


def _serialize(snapshot: FlowSnapshot) -> dict[str, Any]:
    return _snapshot_payload(snapshot).model_dump(mode="json")


async def _bundle() -> RuntimeBundle:
    """表现层只负责注入序列化器；存储装配在 runtime.bootstrap（MUST-06）。"""
    return await get_runtime(await get_service(), _serialize)


def _request_id(request: Request, header: str | None) -> str:
    return header or request.headers.get("X-Request-ID") or uuid.uuid4().hex


@router.post(
    "/runs",
    status_code=202,
    response_model=ApiResponse[dict[str, Any]],
    description="启动一次运行；执行在服务端独立进行，连接断开不取消。",
)
async def start_run(
    request: Request,
    req: StartRunRequest,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> ApiResponse[dict[str, Any]]:
    bundle = await _bundle()
    request_id = _request_id(request, x_request_id)
    record = await bundle.manager.start(
        session_id=req.session_id,
        project=req.project,
        sentence=req.sentence,
        request_id=request_id,
        base_turn_id=req.base_turn_id,
        locale=cast(Locale, req.locale) if req.locale else DEFAULT_LOCALE,
        domain=req.domain,
        style=req.style,
        images=req.images,
    )
    return ApiResponse(
        data={
            "run_id": record.run_id,
            "session_id": record.session_id,
            "status": record.status,
        },
        request_id=request_id,
    )


@router.get(
    "/sessions/{session_id}/stream",
    description="订阅会话事件流；?since=N 只补差，建连先收 seq=0 合成快照。",
)
async def stream_session(
    session_id: str,
    since: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    bundle = await _bundle()
    run = await bundle.runs.latest_for_session(session_id)
    pending = await bundle.interventions.pending(session_id)
    snapshot = EventBus.synthetic_snapshot(
        session_id,
        {
            "session_id": session_id,
            "run": None
            if run is None
            else {
                "run_id": run.run_id,
                "status": run.status,
                "stop_reason": run.stop_reason,
                "ended_at": run.ended_at,
            },
            "pending": [
                {"request_id": item.request_id, "kind": item.kind, "payload": item.payload}
                for item in pending
            ],
            "last_seq": await bundle.bus.last_seq(session_id),
        },
    )

    async def _frames() -> Any:
        async for event in follow(
            bundle.bus,
            session_id,
            since=since,
            snapshot=snapshot,
        ):
            yield sse_frame(event)

    return StreamingResponse(
        _frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/interventions/{request_id}/answer",
    response_model=ApiResponse[dict[str, Any]],
    description="审批/提问应答；第一应答获胜，重复应答返回 6001。",
)
async def answer_intervention(
    request: Request,
    request_id: str,
    req: InterventionAnswerRequest,
) -> ApiResponse[dict[str, Any]]:
    bundle = await _bundle()
    ok = await bundle.interventions.answer(request_id, req.decision, req.answer)
    if not ok:
        raise StateError(
            "该干预已裁决或不存在",
            context={"request_id": request_id},
        )
    return ApiResponse(data={"request_id": request_id, "decision": req.decision})


@router.post(
    "/runs/{run_id}/cancel",
    response_model=ApiResponse[dict[str, Any]],
    description="取消运行；执行体收到 CancelledError 后以 aborted 收尾。",
)
async def cancel_run(run_id: str) -> ApiResponse[dict[str, Any]]:
    bundle = await _bundle()
    cancelled = await bundle.manager.cancel(run_id)
    if not cancelled:
        raise DevPromptError("运行不存在或已结束", code=6003)
    return ApiResponse(data={"run_id": run_id, "cancelled": True})


@router.get(
    "/events",
    response_model=ApiResponse[list[dict[str, Any]]],
    description="冷启动回填：取 seq 之前的事件（分页）。",
)
async def list_events(
    session_id: str,
    before: Annotated[int, Query(ge=1)] = 1 << 30,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> ApiResponse[list[dict[str, Any]]]:
    bundle = await _bundle()
    events = await bundle.bus.history_before(session_id, before, limit=limit)
    return ApiResponse(data=[event.to_wire() for event in events])


@router.post(
    "/sessions/{session_id}/model",
    response_model=ApiResponse[SessionModelResponse],
    description="会话级模型热切换（F10）：写会话覆盖，下一轮生成即生效；空串清除覆盖。",
)
async def switch_session_model(
    request: Request,
    session_id: str,
    req: SessionModelRequest,
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> ApiResponse[SessionModelResponse]:
    service = await get_service()
    data = await service.set_session_model(_USER_ID, session_id, req.model_id)
    return ApiResponse(
        data=SessionModelResponse(
            session_id=str(data.get("session_id", session_id)),
            model_id=str(data.get("model_override", req.model_id)),
        ),
        request_id=_request_id(request, x_request_id),
    )


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ApiResponse[ArtifactResponse],
    description="回读被截断工具的全量输出；内容可能含代码正文，禁止写入日志（MUST-19）。",
)
async def read_artifact(artifact_id: str) -> ApiResponse[ArtifactResponse]:
    content = await read_tool_artifact(artifact_id)
    if content is None:
        raise DevPromptError("工件不存在或已过期（1 小时后清理）", code=6003)
    return ApiResponse(data=ArtifactResponse(artifact_id=artifact_id, content=content))
