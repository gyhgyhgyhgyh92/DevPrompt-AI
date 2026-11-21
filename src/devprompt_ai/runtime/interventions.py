"""审批/提问 broker：注册 pending 并广播，应答走「第一应答获胜」。

推送层不去重（多端都能看到弹框），去重压在存储的条件更新上。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from devprompt_ai.domain.interventions import Intervention, InterventionKind
from devprompt_ai.memory.intervention_store import SQLiteInterventionStore
from devprompt_ai.runtime.events import EventBus


class InterventionBroker:
    def __init__(self, store: SQLiteInterventionStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus

    async def ask(
        self,
        session_id: str,
        *,
        run_id: str = "",
        kind: InterventionKind = "question",
        payload: dict[str, Any] | None = None,
    ) -> Intervention:
        item = await self._store.register(session_id, run_id=run_id, kind=kind, payload=payload)
        await self._bus.append(
            session_id,
            "approval" if kind == "approval" else "ask",
            {"request_id": item.request_id, "kind": kind, "payload": item.payload},
            run_id=run_id,
        )
        return item

    async def answer(self, request_id: str, decision: str, answer: str = "") -> bool:
        """返回是否由本次调用裁决成功；重复应答返回 False（API 层回 409）。"""
        existing = await self._store.get(request_id)
        ok = await self._store.resolve(request_id, decision, answer)
        if ok and existing is not None:
            await self._bus.append(
                existing.session_id,
                "approval.resolved",
                {"request_id": request_id, "decision": decision, "answer": answer},
                run_id=existing.run_id,
            )
        return ok

    async def wait(
        self, request_id: str, *, timeout_s: float = 60.0, interval_s: float = 0.5
    ) -> Intervention | None:
        """阻塞等待裁决（MCP 工具审批用）；超时返回 ``None`` 并按拒绝落库。

        不允许无限等待：调用方在等的是**模型的一次工具调用**，挂死会拖住整轮生成。
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            item = await self._store.get(request_id)
            if item is None or not item.is_pending:
                return item
            if time.monotonic() >= deadline:
                # 用 deny 收尾（decision 合法），answer 里标注超时原因供审计。
                await self._store.resolve(request_id, "deny", "timeout")
                return await self._store.get(request_id)
            await asyncio.sleep(interval_s)

    async def pending(self, session_id: str) -> list[Intervention]:
        return await self._store.pending(session_id)

    async def cancel_pending(self, session_id: str) -> int:
        return await self._store.cancel_pending(session_id)
