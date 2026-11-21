"""Web 路由薄壳（MUST-10）：只做参数收拢 → 调 service → 渲染，零业务逻辑。"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from devprompt_ai.common.i18n import Locale, resolve_locale
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.domain.events import RunEvent
from devprompt_ai.domain.models import TurnRecord
from devprompt_ai.domain.progress import ProgressEvent, ProgressSink
from devprompt_ai.interfaces.api import health
from devprompt_ai.interfaces.api.schemas import (
    ApiResponse,
    AskOptionPayload,
    CostDetailPayload,
    DeliveryGatePayload,
    DomainVerdictPayload,
    FactPayload,
    FlowSnapshotResponse,
    FollowupRequest,
    HealthResponse,
    HistoryItemPayload,
    HistoryUpdateRequest,
    McpServerUpdate,
    ModelCatalogRefreshRequest,
    ModelCatalogResponse,
    OptimizeRequest,
    PagedHistoryItem,
    PagedTurnSummary,
    ProjectDeleteResponse,
    RollbackRequest,
    ScanResponse,
    SettingsResponse,
    SettingsUpdate,
    SymbolPayload,
    TurnDetailPayload,
    TurnSummaryPayload,
    UnknownItemPayload,
    VariantPayload,
)
from devprompt_ai.runtime.bootstrap import get_runtime
from devprompt_ai.runtime.events import BufferedEventSink
from devprompt_ai.service import FlowSnapshot, ForgeService, build_default

logger = logging.getLogger(__name__)

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


def _locale(request: Request) -> Locale:
    """``Accept-Language`` → 界面语言（只做头解析，不含业务判定，MUST-10）。"""
    return resolve_locale(request.headers.get("accept-language"))


def _request_id(request: Request) -> str:
    """X-Request-ID 透传（§3.1）：中间件生成并回写响应头，信封 request_id 取同一值。"""
    return str(getattr(request.state, "request_id", "") or uuid.uuid4().hex)


def _ok(data: DataT, request_id: str) -> ApiResponse[DataT]:
    return ApiResponse(code=0, message="ok", data=data, request_id=request_id)


def _snapshot_payload(snapshot: FlowSnapshot) -> FlowSnapshotResponse:
    """快照渲染（dataclass → 契约模型；VariantDraft 需逐字段镜像）。"""
    variant = snapshot.variant
    target = snapshot.target
    return FlowSnapshotResponse(
        session_id=snapshot.session_id,
        evidence_stale=snapshot.evidence_stale,
        reply_text=snapshot.reply_text,
        delivery_gate=(
            DeliveryGatePayload(
                status=snapshot.delivery_gate.status,
                tone=snapshot.delivery_gate.tone,
                reasons=list(snapshot.delivery_gate.reasons),
                disclosure=snapshot.delivery_gate.disclosure,
            )
            if snapshot.delivery_gate is not None
            else None
        ),
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
        variant=VariantPayload(**variant.model_dump()) if variant is not None else None,
        target=SymbolPayload(name=target.name, path=target.path, line=target.line)
        if target is not None
        else None,
        facts=[
            FactPayload(key=f.key, passed=f.passed, evidence=f.evidence) for f in snapshot.facts
        ],
        cost=CostDetailPayload(**dataclasses.asdict(snapshot.cost)) if snapshot.cost else None,
        message=snapshot.message,
        current_turn_id=snapshot.current_turn_id,
        agent_step=snapshot.agent_step,
        agent_action=snapshot.agent_action,
        agent_elapsed_ms=snapshot.agent_elapsed_ms,
        domain=(
            DomainVerdictPayload(
                domain=str(snapshot.domain.get("domain", "")),
                source=str(snapshot.domain.get("source", "")),
                confidence=float(snapshot.domain.get("confidence", 0.0)),
            )
            if isinstance(snapshot.domain, dict)
            else None
        ),
    )


@router.get("/health")
async def get_health(request: Request) -> ApiResponse[HealthResponse]:
    request_id = _request_id(request)
    report = await health.run_checks(AppConfig())
    return _ok(report, request_id)


async def _event_log(
    service: Any, request_id: str, downstream: ProgressSink | None = None
) -> BufferedEventSink | None:
    """旧入口（/optimize、/optimize/stream）的会话日志出口。

    运行时装配不可用（单测 Fake service、未初始化）时返回 None：Session Log 是旁路，
    缺失不得阻断业务（D-05）。Fake service 没有 config，直接跳过——避免测试触发
    真实 runtime 初始化并把事件写进用户库。
    """
    if getattr(service, "config", None) is None:
        return None
    try:
        # 延迟 import：runtime_routes 在模块级 import 本模块，提前 import 会形成环。
        from devprompt_ai.interfaces.api.runtime_routes import _bundle

        bundle = await _bundle()
        return BufferedEventSink(
            bundle.bus, run_id=request_id, request_id=request_id, downstream=downstream
        )
    except Exception:  # noqa: BLE001 - 观测装配失败不影响主流程
        return None


@router.post(
    "/optimize",
    description="有副作用端点：禁止客户端自动重试（MUST-15，重复提交将产生重复流程）。",
)
async def post_optimize(
    request: Request, req: OptimizeRequest
) -> ApiResponse[FlowSnapshotResponse]:
    request_id = _request_id(request)
    svc = await get_service()
    log = await _event_log(svc, request_id)
    try:
        snapshot = await svc.optimize(
            _USER_ID,
            req.project,
            req.sentence,
            request_id=request_id,
            progress=log,
            session_id=req.session_id,
            base_turn_id=req.base_turn_id,
            locale=_locale(request),
            domain_override=req.domain,
            style=req.style,
            images=req.images,
        )
    except Exception as exc:
        if log is not None:
            await log.fail(
                req.session_id or "",
                code=int(getattr(exc, "code", 0) or 0),
                message=str(exc) or type(exc).__name__,
            )
        raise
    if log is not None:
        await log.finish(
            snapshot.session_id,
            _snapshot_payload(snapshot).model_dump(mode="json"),
            status=snapshot.status,
            state=snapshot.state,
        )
    return _ok(_snapshot_payload(snapshot), request_id)


#: SSE 保活间隔（秒）：LLM 单次调用可能跑满 60s，中间无事件时防代理/浏览器空闲断流。
_STREAM_PING_SECONDS: float = 15.0


class _QueueSink:
    """ProgressEvent → SSE 帧（2026-11-03 从 /optimize/stream 抽出，optimize/followup 共用）。"""

    def __init__(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queue = queue

    async def emit(self, event: ProgressEvent) -> None:
        if event.action is None:
            self._queue.put_nowait({"type": "thought", "text": event.text, "phase": event.phase})
            return
        # detail 已在观测层脱敏（只含仓库相对路径），此处原样转发
        self._queue.put_nowait(
            {
                "type": "action",
                "phase": event.phase,
                "title": event.action.title,
                "detail": event.action.detail,
                "scope": event.action.scope,
                "output": event.action.output,
                # 失败态（2026-11-04）：前端据此渲染错误色与 Exit code，折叠时也看得见
                "status": event.action.status,
                # 真实耗时（2026-11-07）：None 表示未计时，前端据此整段不渲染耗时
                "duration_ms": event.action.duration_ms,
                # 流式呈现（2026-11-15）：动作实例 id + 本次增量片段；旧后端无此二者时行为不变
                "id": event.action.id,
                "delta": event.action.delta,
            }
        )


def _stream_progress(
    request_id: str, producer: Callable[[ProgressSink], Awaitable[FlowSnapshot]]
) -> StreamingResponse:
    """进度流外壳（MUST-10：本层只搬帧，文案与流程都在 service/domain）。

    ``producer`` 拿到 sink 跑业务流程，本函数负责把帧泵出去：thought/action 即时推送、
    ping 心跳保活、终帧 snapshot 或 error。用 POST 而非 EventSource：EventSource 只能 GET，
    而用户原句不能进 URL / 访问日志（MUST-19），故由前端 fetch 读取响应流。
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def _produce() -> None:
        try:
            snapshot = await producer(_QueueSink(queue))
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


@router.post(
    "/optimize/stream",
    description=(
        "流式版 /optimize（SSE）：thought 帧推送文字段落、action 帧推送工具动作卡片，"
        "终帧为 snapshot 或 error。"
        "有副作用端点：禁止客户端自动重试（MUST-15）。"
    ),
)
async def post_optimize_stream(request: Request, req: OptimizeRequest) -> StreamingResponse:
    """优化流程的思考过程流。"""
    request_id = _request_id(request)

    async def _produce(sink: ProgressSink) -> FlowSnapshot:
        svc = await get_service()
        log = await _event_log(svc, request_id, downstream=sink)
        try:
            snapshot = await svc.optimize(
                _USER_ID,
                req.project,
                req.sentence,
                request_id=request_id,
                progress=log or sink,
                session_id=req.session_id,
                locale=_locale(request),
                domain_override=req.domain,
                style=req.style,
                images=req.images,
            )
        except Exception as exc:
            if log is not None:
                await log.fail(
                    req.session_id or "",
                    code=int(getattr(exc, "code", 0) or 0),
                    message=str(exc) or type(exc).__name__,
                )
            raise
        if log is not None:
            await log.finish(
                snapshot.session_id,
                _snapshot_payload(snapshot).model_dump(mode="json"),
                status=snapshot.status,
                state=snapshot.state,
            )
        return snapshot

    return _stream_progress(request_id, _produce)


@router.get("/progress/{flow_id}")
async def get_progress(request: Request, flow_id: str) -> StreamingResponse:
    """SSE 进度流：1s 轮询快照；DONE/ABORTED/ASKING/护栏推送后关闭；客户端断开即停。

    星型拓扑（2026-11-04）：AGENTIC 期间快照 status 为 "running"，**不在关闭集合内**，
    因此 agentic 循环可以持续推送进度而不是中途断流。
    """
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


def _serialize_snapshot(snapshot: FlowSnapshot) -> dict[str, Any]:
    """RuntimeBundle 需要注入快照序列化器（事件落库本身不用它）。"""
    return _snapshot_payload(snapshot).model_dump(mode="json")


async def _append_followup_event(
    session_id: str, event_type: str, payload: dict[str, Any], run_id: str
) -> None:
    """答复路径的事件落库（2026-11-15）：失败只降级为跳过，绝不阻断业务。"""
    try:
        bundle = await get_runtime(await get_service(), _serialize_snapshot)
        await bundle.bus.append(session_id, event_type, payload, run_id=run_id)
    except Exception:  # noqa: BLE001 - 观测 fail-open
        logger.debug("followup.event_append_failed", exc_info=True)


async def _run_followup(
    svc: ForgeService,
    flow_id: str,
    req: FollowupRequest,
    *,
    request_id: str,
    progress: ProgressSink | None = None,
) -> FlowSnapshot:
    """三模式分发（互斥由契约校验保证）：批量答复 / 逃生 / 软护栏裁决（MUST-26）。

    2026-11-15：答复也写 run_events（run.started → stop）。此前第二段（重新研判 + 生成）
    只在 trace 里有记录，Session Log 面板看不到答复后的流程。不写 snapshot 帧——
    终态由进度流的 snapshot 帧负责，避免前端重复应用。
    """
    run_id = f"followup-{request_id}" if request_id else "followup"
    await _append_followup_event(
        flow_id,
        "run.started",
        {"run_id": run_id, "request_id": request_id, "mode": "followup"},
        run_id,
    )
    try:
        if req.escape:
            snapshot = await svc.escape(_USER_ID, flow_id, request_id=request_id)
        elif req.guardrail_action is not None:
            snapshot = await svc.guardrail_confirm(
                _USER_ID, flow_id, req.guardrail_action == "continue", request_id=request_id
            )
        else:
            snapshot = await svc.ask_followup(
                _USER_ID, flow_id, req.answers or {}, request_id=request_id, progress=progress
            )
    except Exception:
        await _append_followup_event(
            flow_id, "stop", {"status": "failed", "state": "aborted"}, run_id
        )
        raise
    await _append_followup_event(
        flow_id,
        "stop",
        {"status": snapshot.status, "state": snapshot.state},
        run_id,
    )
    return snapshot


@router.post("/followup/{flow_id}")
async def post_followup(
    request: Request, flow_id: str, req: FollowupRequest
) -> ApiResponse[FlowSnapshotResponse]:
    """答复 / 逃生 / 护栏裁决（一次性 JSON，保留给非流式调用方）。"""
    request_id = _request_id(request)
    svc = await get_service()
    snapshot = await _run_followup(svc, flow_id, req, request_id=request_id)
    return _ok(_snapshot_payload(snapshot), request_id)


@router.post(
    "/followup/{flow_id}/stream",
    description=(
        "流式版 /followup（SSE）：thought/action 帧推送重新研判与生成过程，"
        "终帧为 snapshot 或 error。"
        "有副作用端点：禁止客户端自动重试（MUST-15）。"
    ),
)
async def post_followup_stream(
    request: Request, flow_id: str, req: FollowupRequest
) -> StreamingResponse:
    """答复后的过程流式推送（2026-11-03）：此前只有一次性 JSON，回答后界面无过程可看。"""
    request_id = _request_id(request)

    async def _produce(sink: ProgressSink) -> FlowSnapshot:
        svc = await get_service()
        return await _run_followup(svc, flow_id, req, request_id=request_id, progress=sink)

    return _stream_progress(request_id, _produce)


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
    request: Request,
    session_id: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ApiResponse[PagedTurnSummary]:
    """会话的轮次摘要（升序）；不含原句与方案正文。

    分页：``offset`` 从最新一轮往回数（前端「加载更早」）。
    """
    request_id = _request_id(request)
    svc = await get_service()
    page = await svc.list_turns(_USER_ID, session_id, limit=limit, offset=offset)
    return _ok(
        PagedTurnSummary(
            items=[_turn_summary_payload(turn) for turn in page.items],
            has_more=page.has_more,
            limit=page.limit,
            offset=page.offset,
        ),
        request_id,
    )


def _steps_of(turn: TurnRecord) -> list[dict[str, Any]]:
    """本轮动作序列（随摘要落库，见 ``build_context.summary_from_turn``）。"""
    raw = turn.summary.get("steps") if isinstance(turn.summary, dict) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _clip_output(text: str, limit: int = 2000) -> str:
    """工具输出截断：/turns 是详情接口，不能让单帧 output 无限放大响应体。"""
    return text if len(text) <= limit else f"{text[:limit]}\n…（已截断）"


def _segments_for_turn(events: list[RunEvent], turn_id: str) -> list[RunEvent]:
    """按 run.started 切段，并用 snapshot.current_turn_id 归属到具体轮次。

    没有 snapshot 的段（followup 的重新研判 + 生成）归到「此前最近一轮」——
    它本来就发生在该轮之后、同一 turn 之内。
    """
    segments: list[list[RunEvent]] = []
    current: list[RunEvent] = []
    for event in events:
        if event.type == "run.started":
            if current:
                segments.append(current)
            current = [event]
        elif current:
            current.append(event)
    if current:
        segments.append(current)

    picked: list[RunEvent] = []
    last_turn = ""
    for segment in segments:
        owner = ""
        for event in segment:
            if event.type != "snapshot":
                continue
            candidate = str(event.payload.get("current_turn_id") or "")
            if candidate:
                owner = candidate
        if owner:
            last_turn = owner
        if (owner or last_turn) == turn_id:
            picked.extend(segment)
    return picked


def _thinking_payload(events: list[RunEvent]) -> list[dict[str, Any]]:
    """事件段 → 前端 ThinkingItem 同构列表（thought 文字 + action 卡片）。"""
    shots: list[dict[str, Any]] = []
    for event in events:
        phase = str(event.payload.get("phase") or "")
        if event.type == "thought":
            text = str(event.payload.get("text") or "").strip()
            if text:
                shots.append(
                    {"id": f"ev-{event.seq}", "kind": "text", "text": text, "phase": phase}
                )
            continue
        if event.type != "action":
            continue
        shots.append(
            {
                "id": f"ev-{event.seq}",
                "kind": "action",
                "phase": phase,
                "title": str(event.payload.get("title") or ""),
                "detail": str(event.payload.get("detail") or ""),
                "scope": str(event.payload.get("scope") or ""),
                "output": _clip_output(str(event.payload.get("output") or "")),
                "status": str(event.payload.get("status") or "ok"),
                "duration_ms": event.payload.get("duration_ms"),
            }
        )
    return shots


async def _turn_thinking(turn: TurnRecord) -> list[dict[str, Any]]:
    """从 run_events 重建历史轮的完整思考帧（2026-11-15）。

    这不是新增落库：流式端点本就把 thought/action（含工具 output）写进 run_events。
    详情接口从中还原，历史轮即可拥有与当前轮同构的过程时间线。读取失败 fail-open
    返回空数组——观测旁路不得阻断详情。
    """
    try:
        bundle = await get_runtime(await get_service(), _serialize_snapshot)
        total = await bundle.bus.last_seq(turn.session_id)
        if total <= 0:
            return []
        events: list[RunEvent] = []
        cursor = total + 1
        while cursor > 1:
            batch = await bundle.bus.history_before(turn.session_id, cursor, limit=500)
            if not batch:
                break
            events = batch + events
            cursor = batch[0].seq
    except Exception:  # noqa: BLE001 - 观测旁路 fail-open
        logger.warning("turn.thinking_load_failed", exc_info=True)
        return []
    return _thinking_payload(_segments_for_turn(events, turn.turn_id))


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
            steps=_steps_of(turn),
            thinking=await _turn_thinking(turn),
        ),
        request_id,
    )


@router.get("/history")
async def get_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ApiResponse[PagedHistoryItem]:
    """T6-11 转正：脱敏会话摘要（id/时间/state/项目名/标题/置顶，无原句明文，MUST-19）。

    分页：置顶优先 + updated_at 倒序后，从第 ``offset`` 条起取 ``limit`` 条。
    """
    request_id = _request_id(request)
    svc = await get_service()
    page = await svc.list_history(_USER_ID, limit=limit, offset=offset)
    return _ok(
        PagedHistoryItem(
            items=[
                HistoryItemPayload(
                    session_id=i.session_id,
                    state=i.state,
                    project=i.project,
                    updated_at=i.updated_at,
                    title=i.title,
                    pinned=i.pinned,
                    project_root=i.project_root,
                )
                for i in page.items
            ],
            has_more=page.has_more,
            limit=page.limit,
            offset=page.offset,
        ),
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


@router.post("/history/{session_id}/rollback")
async def rollback_session(
    request: Request, session_id: str, req: RollbackRequest
) -> ApiResponse[FlowSnapshotResponse]:
    """撤销到某一轮（2026-11-05）：物理删除其后轮次，会话回到该轮完成时的状态。

    显式破坏性操作（MUST-32 修订）：删除不可恢复，前端必须二次确认后才能调用。
    """
    request_id = _request_id(request)
    svc = await get_service()
    snapshot = await svc.rollback_to_turn(_USER_ID, session_id, req.turn_id, request_id=request_id)
    return _ok(_snapshot_payload(snapshot), request_id)


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
    return _ok(SettingsResponse(**await svc.get_settings(_locale(request))), request_id)


@router.put("/settings")
async def put_settings(request: Request, req: SettingsUpdate) -> ApiResponse[SettingsResponse]:
    """T6-11：模型段写设置文件（0600），流程段写 app_settings 表；密钥恒脱敏返回。"""
    request_id = _request_id(request)
    svc = await get_service()
    view = await svc.update_settings(req.model_dump(exclude_none=True), request_id=request_id)
    return _ok(SettingsResponse(**view), request_id)


@router.post("/settings/mcp/test")
async def test_mcp_server(request: Request, req: McpServerUpdate) -> ApiResponse[dict[str, Any]]:
    """测试连接（2026-11-21）：连一次、列工具、立即断开；失败只回报不抛。"""
    from devprompt_ai.domain.mcp.models import McpServerConfig

    request_id = _request_id(request)
    svc = await get_service()
    config = McpServerConfig(**{**req.model_dump(exclude_none=True), "enabled": True})
    result = await svc.test_mcp_server(config)
    return _ok(result, request_id)


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
