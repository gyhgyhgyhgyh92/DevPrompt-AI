"""Trace 采集器：上下文隔离、批量落库、失败降级（2026-11-12）。

- 使用 ContextVar 绑定当前 turn，天然隔离并发请求；
- 先缓冲、按阈值/轮次结束批量写入，避免每条事件一次事务；
- 写失败不阻断业务，记固定事件并把后续事件标 partial。
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from devprompt_ai.domain.obs.contract.trace import (
    TraceEvent,
    TraceKind,
    TraceStatus,
    hash_key,
    mask_secrets,
)
from devprompt_ai.domain.obs.contract.version import TRACE_SCHEMA_VERSION
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.observability.logging import emit

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _TraceContext:
    trace_id: str
    session_id: str
    turn_id: str
    turn_index: int
    run_id: str


class TraceCollectorImpl:
    """TraceCollector 的默认实现；``enabled=False`` 时所有方法近似空操作。"""

    def __init__(
        self,
        store: SQLiteTraceStore,
        *,
        enabled: bool = True,
        buffer_size: int = 20,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._buffer_size = max(1, buffer_size)
        self._ctx: ContextVar[_TraceContext | None] = ContextVar("trace_ctx", default=None)
        self._action_parent: ContextVar[str] = ContextVar("trace_action_parent", default="")
        self._seq: dict[str, int] = {}
        self._buffers: dict[str, list[TraceEvent]] = {}
        self._partial: set[str] = set()
        self._listeners: list[Any] = []

    def add_listener(self, listener: Any) -> None:
        self._listeners.append(listener)

    @property
    def enabled(self) -> bool:
        """运行期开关（2026-11-12）：设置页改开关后即时生效，无需重建包装器。"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    async def start_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_index: int,
        sentence: str,
        project_root: str,
        inherited_target: str = "",
        clarifications: dict[str, str] | None = None,
        run_id: str = "",
        request_id: str = "",
        session_data: dict[str, Any] | None = None,
    ) -> str:
        if not self._enabled:
            return ""
        segment = (request_id or "turn")[:8]
        trace_id = f"{session_id}:{turn_index}:{segment}"
        self._ctx.set(
            _TraceContext(
                trace_id=trace_id,
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                run_id=run_id,
            )
        )
        self._seq[trace_id] = 0
        self._buffers.setdefault(trace_id, [])
        input_hash = hash_key(sentence, project_root, inherited_target, clarifications or {})
        await self.record(
            TraceKind.TURN_START.value,
            "turn",
            input={
                "sentence": sentence,
                "project_root": project_root,
                "inherited_target": inherited_target,
                "clarifications": clarifications or {},
                "session_data": session_data or {},
            },
            attributes={"input_hash": input_hash, "run_id": run_id, "request_id": request_id},
        )
        return trace_id

    async def record(
        self,
        kind: str,
        name: str,
        *,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        status: str = TraceStatus.OK.value,
        error: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        parent_id: str = "",
    ) -> str:
        ctx = self._ctx.get()
        if not self._enabled or ctx is None:
            return ""
        seq = self._seq.get(ctx.trace_id, 0) + 1
        self._seq[ctx.trace_id] = seq
        event = TraceEvent(
            event_id=uuid.uuid4().hex,
            trace_id=ctx.trace_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            turn_index=ctx.turn_index,
            run_id=ctx.run_id,
            seq=seq,
            parent_id=parent_id or self._action_parent.get(),
            kind=kind,
            name=name,
            status=TraceStatus.PARTIAL.value if ctx.trace_id in self._partial else status,
            started_at=_now(),
            ended_at=_now(),
            duration_ms=int((attributes or {}).get("duration_ms", 0) or 0),
            input=mask_secrets(input or {}),
            output=mask_secrets(output or {}),
            error=mask_secrets(error or {}),
            attributes=mask_secrets(attributes or {}),
            schema_version=TRACE_SCHEMA_VERSION,
        )
        self._buffers.setdefault(ctx.trace_id, []).append(event)
        if len(self._buffers[ctx.trace_id]) >= self._buffer_size:
            await self.flush(ctx.trace_id)
        return event.event_id

    def set_action_parent(self, event_id: str) -> None:
        self._action_parent.set(event_id)

    def reset_action_parent(self) -> None:
        self._action_parent.set("")

    async def end_turn(
        self,
        *,
        state: str,
        status: str = "ok",
        snapshot: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        ctx = self._ctx.get()
        if not self._enabled or ctx is None:
            return
        await self.record(
            TraceKind.TURN_END.value,
            "turn",
            output={"state": state, "snapshot": snapshot or {}},
            status=status,
            error=error or {},
        )
        await self.flush(ctx.trace_id)
        self._ctx.set(None)
        self._action_parent.set("")
        for listener in self._listeners:
            try:
                await listener.on_trace_completed(ctx.trace_id, ctx.session_id)
            except Exception:  # noqa: BLE001 - 监听器失败不得影响业务
                logger.warning("trace.listener_failed", exc_info=True)

    async def flush(self, trace_id: str = "") -> None:
        trace_ids = [trace_id] if trace_id else list(self._buffers)
        for tid in trace_ids:
            batch = self._buffers.get(tid, [])
            if not batch:
                continue
            self._buffers[tid] = []
            try:
                await self._store.append_events(batch)
            except Exception:  # noqa: BLE001 - 观测失败不阻断业务（fail-open）
                self._partial.add(tid)
                logger.warning("trace.write_failed", exc_info=True)
                try:
                    emit("trace.write_failed", trace_id=tid, count=len(batch))
                except Exception:  # noqa: BLE001 - 连失败事件都不能外抛（D-02）
                    logger.warning("trace.write_failed_emit_error", exc_info=True)

    async def flush_all(self) -> None:
        await self.flush()


class NullTraceCollector:
    """测试/关闭模块时的空实现（零 I/O）。"""

    def add_listener(self, listener: Any) -> None:
        return None

    async def start_turn(self, **_meta: Any) -> str:
        return ""

    async def record(self, *_args: Any, **_kwargs: Any) -> str:
        return ""

    def set_action_parent(self, _event_id: str) -> None:
        return None

    def reset_action_parent(self) -> None:
        return None

    async def end_turn(self, **_meta: Any) -> None:
        return None

    async def flush(self, _trace_id: str = "") -> None:
        return None

    async def flush_all(self) -> None:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
