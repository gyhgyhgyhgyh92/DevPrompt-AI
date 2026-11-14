"""运行管理器：执行体与 HTTP 连接彻底解耦。

连接断开不再取消执行——这是多端接入的前提（旧实现 `routes.py:240-245` 会 cancel）。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale
from devprompt_ai.domain.agent.stop_reason import StopReason, snapshot_stop_reason
from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.domain.runs import RunRecord
from devprompt_ai.memory.run_store import SQLiteRunStore
from devprompt_ai.runtime.events import EventBus, EventSink
from devprompt_ai.runtime.sessions import SessionPool
from devprompt_ai.service import FlowSnapshot, ForgeService

#: 快照序列化由 API 层注入，避免 runtime 反向依赖 interfaces。
SnapshotSerializer = Callable[[FlowSnapshot], dict[str, Any]]

#: 取消后有界等待：让工具批次把结果写完，避免 tool_result 与 tool_calls 脱节。
_ABORT_DRAIN_S: float = 6.0


class RunManager:
    def __init__(
        self,
        *,
        service: ForgeService,
        bus: EventBus,
        runs: SQLiteRunStore,
        pool: SessionPool,
        serialize: SnapshotSerializer,
        user_id: str = "local",
    ) -> None:
        self._service = service
        self._bus = bus
        self._runs = runs
        self._pool = pool
        self._serialize = serialize
        self._user_id = user_id
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(
        self,
        *,
        session_id: str,
        project: str,
        sentence: str,
        request_id: str,
        base_turn_id: str = "",
        locale: Locale = DEFAULT_LOCALE,
    ) -> RunRecord:
        if not session_id.strip():
            raise DevPromptError("session_id 不能为空", code=2001)
        if not sentence.strip() and not base_turn_id.strip():
            raise DevPromptError("sentence 与 base_turn_id 至少给一个", code=2001)
        self._pool.sweep()
        if self._pool.active_run(session_id) is not None:
            raise StateError(
                "同一会话已有执行中的运行",
                context={"session_id": session_id},
            )

        run_id = uuid.uuid4().hex
        self._pool.try_acquire(session_id, run_id)
        await self._runs.create(
            run_id=run_id,
            session_id=session_id,
            turn_index=0,
            request_id=request_id,
        )
        await self._bus.append(
            session_id,
            "run.started",
            {"run_id": run_id, "request_id": request_id},
            run_id=run_id,
        )
        task = asyncio.create_task(
            self._execute(
                run_id=run_id,
                session_id=session_id,
                project=project,
                sentence=sentence,
                request_id=request_id,
                base_turn_id=base_turn_id,
                locale=locale,
            )
        )
        self._tasks[run_id] = task
        self._pool.attach_task(session_id, task)
        record = await self._runs.get(run_id)
        if record is None:  # pragma: no cover - 刚插入必然存在
            raise DevPromptError("运行记录创建失败", code=9001)
        return record

    async def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        # 有界 drain：只停止 await，工具批次仍在跑；不等它收尾会让结果与调用脱节。
        await asyncio.wait({task}, timeout=_ABORT_DRAIN_S)
        return True

    async def _execute(
        self,
        *,
        run_id: str,
        session_id: str,
        project: str,
        sentence: str,
        request_id: str,
        base_turn_id: str,
        locale: Locale,
    ) -> None:
        sink = EventSink(self._bus, session_id, run_id)
        try:
            config = getattr(self._service, "config", None)
            timeout = float(getattr(config, "run_timeout_seconds", 900.0))
            snapshot = await asyncio.wait_for(
                self._service.optimize(
                    self._user_id,
                    project,
                    sentence,
                    request_id=request_id,
                    progress=sink,
                    session_id=session_id,
                    base_turn_id=base_turn_id,
                    locale=locale,
                    # 前端在 POST /runs 前用 crypto.randomUUID() 生成 session_id，
                    # 执行侧按该 id 建容器（D-04），否则新会话直接 6003。
                    create_session=True,
                ),
                timeout=timeout,
            )
            payload = self._serialize(snapshot)
            reason = snapshot_stop_reason(
                str(payload.get("status", "done")), str(payload.get("state", ""))
            )
            await self._bus.append(session_id, "snapshot", payload, run_id=run_id)
            await self._bus.append(
                session_id,
                "stop",
                {
                    "status": payload.get("status", "done"),
                    "state": payload.get("state", ""),
                    "stop_reason": reason.value,
                },
                run_id=run_id,
            )
            await self._runs.finish(run_id, "done", stop_reason=reason.value)
        except asyncio.CancelledError:
            await self._bus.append(
                session_id,
                "stop",
                {"status": "aborted", "reason": StopReason.USER_INTERRUPT.value},
                run_id=run_id,
            )
            await self._runs.finish(run_id, "aborted", stop_reason=StopReason.USER_INTERRUPT.value)
            raise
        except TimeoutError:
            # A9 看门狗：run 级硬上限，以可归因的 watchdog-stall 收尾。
            await self._bus.append(
                session_id,
                "error",
                {"code": 5011, "message": "运行超过单次上限", "request_id": request_id},
                run_id=run_id,
            )
            await self._runs.finish(run_id, "aborted", stop_reason=StopReason.WATCHDOG_STALL.value)
        except DevPromptError as exc:
            await self._bus.append(
                session_id,
                "error",
                {
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": request_id,
                },
                run_id=run_id,
            )
            await self._runs.finish(
                run_id,
                "error",
                stop_reason=StopReason.STREAM_ERROR.value,
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
        except Exception as exc:  # noqa: BLE001 - 失败必须变成 error 事件，不能裸断
            await self._bus.append(
                session_id,
                "error",
                {"code": 9001, "message": type(exc).__name__, "request_id": request_id},
                run_id=run_id,
            )
            await self._runs.finish(
                run_id,
                "error",
                stop_reason=StopReason.STREAM_ERROR.value,
                error_code=9001,
                error_message=type(exc).__name__,
            )
        finally:
            self._tasks.pop(run_id, None)
            self._pool.release(session_id)
