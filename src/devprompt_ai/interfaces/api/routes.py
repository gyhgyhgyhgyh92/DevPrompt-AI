"""Web 路由薄壳（MUST-10）：只做参数收拢 → 调 service → 渲染，零业务逻辑。"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.domain.models import TurnRecord
from devprompt_ai.domain.progress import ProgressEvent
from devprompt_ai.interfaces.api import health
from devprompt_ai.interfaces.api.schemas import (
    ApiResponse,
    AskOptionPayload,
    CostDetailPayload,
    FactPayload,
    FlowSnapshotResponse,
    FollowupRequest,
    HealthResponse,
    HistoryItemPayload,
    HistoryUpdateRequest,
    ModelCatalogRefreshRequest,
    ModelCatalogResponse,
    OptimizeRequest,
    ProjectDeleteResponse,
    RankingViewPayload,
    ScanResponse,
    SettingsResponse,
    SettingsUpdate,
    SymbolPayload,
    TurnDetailPayload,
    TurnSummaryPayload,
    UnknownItemPayload,
    VariantPayload,
)
from devprompt_ai.service import FlowSnapshot, ForgeService, build_default

DataT = TypeVar("DataT")

router = APIRouter(prefix="/api/v1")

_USER_ID = "local"

_service: ForgeService | None = None


async def get_service() -> ForgeService:
    """懒加载单例：复用 service.build_default 组装（MUST-10 单一业务来源）。"""
    global _service
    if _service is None:
        cfg = AppConfig()
        cfg.validate()
        _service = await build_default(cfg)
    return _service


def _request_id(request: Request) -> str:
    """X-Request-ID 透传（§3.1）：中间件生成并回写响应头，信封 request_id 取同一值。"""
    return str(getattr(request.state, "request_id", "") or uuid.uuid4().hex)


def _ok(data: DataT, request_id: str) -> ApiResponse[DataT]:
    return ApiResponse(code=0, message="ok", data=data, request_id=request_id)


def _snapshot_payload(snapshot: FlowSnapshot) -> FlowSnapshotResponse:
    """快照渲染（dataclass → 契约模型；VariantDraft/RankingView 需逐字段镜像）。"""
    ranking = snapshot.ranking
    target = snapshot.target
    return FlowSnapshotResponse(
        session_id=snapshot.session_id,
        status=snapshot.status,
        state=snapshot.state,
        questions=[
            UnknownItemPayload(
                key=q.key,
                reason=q.reason,
                best_guess=q.best_guess,
                ask=q.ask,
                header=q.header,
                options=[
                    AskOptionPayload(label=item.label, description=item.description)
                    for item in q.options
                ],
                multi_select=q.multi_select,
            )
            for q in snapshot.questions
        ],
        cleared=snapshot.cleared,
        variants=[VariantPayload(**v.model_dump()) for v in snapshot.variants],
        ranking=RankingViewPayload(**dataclasses.asdict(ranking)) if ranking is not None else None,
        target=SymbolPayload(name=target.name, path=target.path, line=target.line)
        if target is not None
        else None,
        facts=[
            FactPayload(key=f.key, passed=f.passed, evidence=f.evidence) for f in snapshot.facts
        ],
        cost=CostDetailPayload(**dataclasses.asdict(snapshot.cost)) if snapshot.cost else None,
        message=snapshot.message,
    )


@router.get("/health")
async def get_health(request: Request) -> ApiResponse[HealthResponse]:
    request_id = _request_id(request)
    report = await health.run_checks(AppConfig())
    return _ok(report, request_id)


@router.post(
    "/optimize",
    description="有副作用端点：禁止客户端自动重试（MUST-15，重复提交将产生重复流程）。",
)
async def post_optimize(
    request: Request, req: OptimizeRequest
) -> ApiResponse[FlowSnapshotResponse]:
    request_id = _request_id(request)
    svc = await get_service()
    snapshot = await svc.optimize(
        _USER_ID, req.project, req.sentence, request_id=request_id, session_id=req.session_id
    )
    return _ok(_snapshot_payload(snapshot), request_id)


#: SSE 保活间隔（秒）：LLM 单次调用可能跑满 60s，中间无事件时防代理/浏览器空闲断流。
_STREAM_PING_SECONDS: float = 15.0


@router.post(
    "/optimize/stream",
    description=(
        "流式版 /optimize（SSE）：thought 帧推送文字段落、action 帧推送工具动作卡片，"
        "终帧为 snapshot 或 error。"
        "有副作用端点：禁止客户端自动重试（MUST-15）。"
    ),
)
async def post_optimize_stream(request: Request, req: OptimizeRequest) -> StreamingResponse:
    """思考过程流式端点（MUST-10：本层只搬帧，文案与流程都在 service/domain）。

    用 POST 而非 EventSource：EventSource 只能 GET，而用户原句不能进 URL / 访问日志
    （MUST-19），故由前端 fetch 读取响应流。
    """
    request_id = _request_id(request)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    class _QueueSink:
        async def emit(self, event: ProgressEvent) -> None:
            if event.action is None:
                queue.put_nowait({"type": "thought", "text": event.text, "phase": event.phase})
                return
            # detail 已在观测层脱敏（只含仓库相对路径），此处原样转发
            queue.put_nowait(
                {
                    "type": "action",
                    "phase": event.phase,
                    "title": event.action.title,
                    "detail": event.action.detail,
                    "scope": event.action.scope,
                    "output": event.action.output,
                }
            )

    async def _produce() -> None:
        try:
            svc = await get_service()
            snapshot = await svc.optimize(
                _USER_ID,
                req.project,
                req.sentence,
                request_id=request_id,
                progress=_QueueSink(),
                session_id=req.session_id,
            )
            payload = _snapshot_payload(snapshot).model_dump(mode="json")
            queue.put_nowait({"type": "snapshot", "data": payload})
        except asyncio.CancelledError:
            raise  # 客户端断流：交由 service 的 CancelledError 分支置 ABORTED
        except Exception as exc:  # noqa: BLE001 - 失败必须变成 error 帧，不能裸断流
            queue.put_nowait(
                {
                    "type": "error",
                    "code": int(getattr(exc, "code", 0) or 0),
                    "message": str(exc) or type(exc).__name__,
                    "request_id": request_id,
                }
            )

    async def _events() -> AsyncIterator[str]:
        task = asyncio.create_task(_produce())
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=_STREAM_PING_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
                if frame["type"] in ("snapshot", "error"):
                    return
        finally:
            # 客户端断开或正常收尾：确保后台任务不会残留（取消后 service 置 ABORTED）
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.get("/progress/{flow_id}")
async def get_progress(request: Request, flow_id: str) -> StreamingResponse:
    """SSE 进度流：1s 轮询快照；DONE/ABORTED/ASKING/护栏推送后关闭；客户端断开即停。"""
    request_id = _request_id(request)

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
                    err: ApiResponse[None] = ApiResponse(
                        code=exc.code, message=str(exc), request_id=request_id
                    )
                    yield f"data: {err.model_dump_json()}\n\n"
                return
            yield f"data: {_snapshot_payload(snapshot).model_dump_json()}\n\n"
            if snapshot.state in ("DONE", "ABORTED") or snapshot.status in ("ask", "guardrail"):
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.post("/followup/{flow_id}")
async def post_followup(
    request: Request, flow_id: str, req: FollowupRequest
) -> ApiResponse[FlowSnapshotResponse]:
    """三模式分发（互斥由契约校验保证）：批量答复 / 逃生 / 软护栏裁决（MUST-26）。"""
    request_id = _request_id(request)
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
async def get_result(request: Request, flow_id: str) -> ApiResponse[FlowSnapshotResponse]:
    request_id = _request_id(request)
    svc = await get_service()
    snapshot = await svc.resume(_USER_ID, flow_id, request_id=request_id)
    return _ok(_snapshot_payload(snapshot), request_id)


def _turn_summary_payload(turn: TurnRecord) -> TurnSummaryPayload:
    """turn → 契约摘要（summary 为空时字段留空，不猜）。"""
    summary = turn.summary if isinstance(turn.summary, dict) else {}
    raw_open = summary.get("open")
    open_items = [str(item) for item in raw_open] if isinstance(raw_open, list) else []
    return TurnSummaryPayload(
        turn_id=turn.turn_id,
        turn_index=turn.turn_index,
        state=turn.state,
        target=str(summary.get("target", "")),
        conclusion=str(summary.get("conclusion", "")),
        open_items=open_items,
        created_at=turn.created_at,
    )


@router.get("/history/{session_id}/turns")
async def get_session_turns(
    request: Request, session_id: str
) -> ApiResponse[list[TurnSummaryPayload]]:
    """会话的轮次摘要（升序）；不含原句与方案正文。"""
    request_id = _request_id(request)
    svc = await get_service()
    turns = await svc.list_turns(_USER_ID, session_id)
    return _ok([_turn_summary_payload(turn) for turn in turns], request_id)


@router.get("/turns/{turn_id}")
async def get_turn(request: Request, turn_id: str) -> ApiResponse[TurnDetailPayload]:
    """单轮全文（历史轮次展开时懒加载）。"""
    request_id = _request_id(request)
    svc = await get_service()
    try:
        turn = await svc.load_turn(_USER_ID, turn_id)
    except StateError as exc:
        return ApiResponse(code=exc.code, message=str(exc), request_id=request_id)
    base = _turn_summary_payload(turn)
    return _ok(
        TurnDetailPayload(
            **base.model_dump(),
            input=turn.input,
            variants=[VariantPayload(**item) for item in turn.output],
            facts=[FactPayload(**item) for item in turn.facts],
        ),
        request_id,
    )


@router.get("/history")
async def get_history(request: Request) -> ApiResponse[list[HistoryItemPayload]]:
    """T6-11 转正：脱敏会话摘要（id/时间/state/项目名/标题/置顶，无原句明文，MUST-19）。"""
    request_id = _request_id(request)
    svc = await get_service()
    items = await svc.list_history(_USER_ID)
    return _ok(
        [
            HistoryItemPayload(
                session_id=i.session_id,
                state=i.state,
                project=i.project,
                updated_at=i.updated_at,
                title=i.title,
                pinned=i.pinned,
                project_root=i.project_root,
            )
            for i in items
        ],
        request_id,
    )


@router.patch("/history/{session_id}")
async def patch_history(
    request: Request, session_id: str, req: HistoryUpdateRequest
) -> ApiResponse[None]:
    """会话管理（T1.4）：重命名/置顶——None 字段不提交（exclude_none）；一致性由后续 GET 保证。"""
    request_id = _request_id(request)
    svc = await get_service()
    payload = req.model_dump(exclude_none=True)
    if "title" in payload:
        await svc.rename_session(_USER_ID, session_id, payload["title"])
    if "pinned" in payload:
        await svc.pin_session(_USER_ID, session_id, payload["pinned"])
    return _ok(None, request_id)


@router.delete("/history/{session_id}")
async def delete_history(request: Request, session_id: str) -> ApiResponse[None]:
    """会话管理（T1.4）：删除会话。"""
    request_id = _request_id(request)
    svc = await get_service()
    await svc.delete_session(_USER_ID, session_id)
    return _ok(None, request_id)


@router.delete("/history")
async def delete_project_history(
    request: Request, project_root: str = ""
) -> ApiResponse[ProjectDeleteResponse]:
    """项目级批量删除（2026-11-01）：删该 project_root 下全部会话记录，磁盘文件不动。"""
    request_id = _request_id(request)
    svc = await get_service()
    deleted = await svc.delete_project_sessions(_USER_ID, project_root)
    return _ok(ProjectDeleteResponse(deleted=deleted), request_id)


@router.get("/settings")
async def get_settings(request: Request) -> ApiResponse[SettingsResponse]:
    request_id = _request_id(request)
    svc = await get_service()
    return _ok(SettingsResponse(**await svc.get_settings()), request_id)


@router.put("/settings")
async def put_settings(request: Request, req: SettingsUpdate) -> ApiResponse[SettingsResponse]:
    """T6-11：模型段写设置文件（0600），流程段写 app_settings 表；密钥恒脱敏返回。"""
    request_id = _request_id(request)
    svc = await get_service()
    view = await svc.update_settings(req.model_dump(exclude_none=True), request_id=request_id)
    return _ok(SettingsResponse(**view), request_id)


@router.get("/settings/models/catalog")
async def get_model_catalog(
    request: Request, provider_id: str
) -> ApiResponse[ModelCatalogResponse]:
    """读某供应商的模型目录（落库快照，不联网）。

    2026-10-18 供应商中心化重构：键从 ``entry_id`` 改为 ``provider_id``——目录挂在
    端点而非条目上，刚配好还没勾选模型的供应商也读得到自己的目录。
    """
    request_id = _request_id(request)
    svc = await get_service()
    provider, base_url, _ = svc.provider_catalog_target(provider_id)
    view = await svc.read_model_catalog(provider, base_url, request_id=request_id)
    return _ok(ModelCatalogResponse(**view), request_id)


@router.post("/settings/models/catalog/refresh")
async def refresh_model_catalog(
    request: Request, req: ModelCatalogRefreshRequest
) -> ApiResponse[ModelCatalogResponse]:
    """刷新模型列表：现场调该端点的 `/models` → 落库 → 返回合并结果。

    薄壳：参数收拢 → 调 service → 渲染（MUST-10）。api_key 由 provider_id 在
    settings.json（0600）里取，明文密钥不进请求体。
    """
    request_id = _request_id(request)
    svc = await get_service()
    provider, base_url, api_key = svc.provider_catalog_target(req.provider_id, with_key=True)
    view = await svc.refresh_model_catalog(provider, base_url, api_key, request_id=request_id)
    return _ok(ModelCatalogResponse(**view), request_id)


@router.get("/project/scan")
async def get_project_scan(request: Request, project: str) -> ApiResponse[ScanResponse]:
    request_id = _request_id(request)
    svc = await get_service()
    try:
        stats = await svc.scan_project(project)
    except DevPromptError as exc:
        # 路径/工具类失败走信封错误码（2001/2004），不给前端裸 500 —— 否则前端只能
        # 猜「路径不存在」，真实原因被掩盖（2026-10-20 实测）
        return ApiResponse(code=exc.code, message=str(exc), request_id=request_id)
    return _ok(ScanResponse(**stats), request_id)
