"""Replay 模块应用服务：verify（单 Trace 自比对）与 compare（双 Trace 对比）。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import ReplayNodeResult, ReplayRunRecord
from devprompt_ai.domain.obs.replay.compare import (
    compare_snapshots,
    compare_streams,
    compare_two_traces,
    final_snapshot,
)
from devprompt_ai.harness.obs.memory_collector import MemoryTraceCollector
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.replay_execution import ReplayExecutionAdapter


class ReplayService:
    def __init__(
        self,
        trace_store: SQLiteTraceStore,
        replay_store: SQLiteReplayStore,
        cfg: AppConfig,
        *,
        enabled: bool = True,
    ) -> None:
        self._trace_store = trace_store
        self._replay_store = replay_store
        self._cfg = cfg
        self.enabled = enabled

    async def startup(self) -> None:
        await self._replay_store.init_schema()

    async def create(
        self, *, mode: str, left_trace_id: str, right_trace_id: str = ""
    ) -> ReplayRunRecord:
        if mode not in {"verify", "compare"}:
            raise ValueError("mode 必须是 verify 或 compare")
        left = await self._trace_store.list_trace_events(left_trace_id)
        if not left:
            raise ValueError(f"Trace 不存在：{left_trace_id}")
        right = (
            await self._trace_store.list_trace_events(right_trace_id) if mode == "compare" else []
        )
        if mode == "compare":
            if not right:
                raise ValueError(f"Trace 不存在：{right_trace_id}")
            left_meta = await self._trace_store.trace_summary(left_trace_id)
            right_meta = await self._trace_store.trace_summary(right_trace_id)
            if (
                left_meta is not None
                and right_meta is not None
                and left_meta.input_hash != right_meta.input_hash
            ):
                raise ValueError("两条 Trace 的 input_hash 不一致，不能做版本对比")

        record = ReplayRunRecord(
            run_id=uuid.uuid4().hex,
            mode=mode,
            status="running",
            left_trace_id=left_trace_id,
            right_trace_id=right_trace_id,
            matched_nodes=0,
            mismatched_nodes=0,
            missing_nodes=0,
            result={},
            error={},
            created_at=_now(),
            ended_at="",
        )
        await self._replay_store.create_run(record, [])
        asyncio.create_task(self._execute(record, left, right))
        return record

    async def _execute(
        self,
        record: ReplayRunRecord,
        left: list[Any],
        right: list[Any],
    ) -> None:
        try:
            if record.mode == "compare":
                nodes, final = compare_two_traces(left, right)
                actual_snapshot: dict[str, Any] = final
            else:
                collector = MemoryTraceCollector()
                adapter = ReplayExecutionAdapter(self._cfg)
                actual_snapshot = await asyncio.wait_for(
                    adapter.execute(left, collector=collector),
                    timeout=self._cfg.obs_replay_timeout_seconds,
                )
                nodes = compare_streams(left, collector.events)
                final = compare_snapshots(final_snapshot(left), actual_snapshot)
            matched = sum(1 for node in nodes if node.match)
            mismatched = sum(1 for node in nodes if not node.match)
            missing = sum(1 for node in nodes if "missing" in node.diff)
            status = "matched" if mismatched == 0 else "diverged"
            await self._replay_store.save_nodes(record.run_id, nodes)
            await self._replay_store.finish_run(
                record.run_id,
                status=status,
                matched=matched,
                mismatched=mismatched,
                missing=missing,
                result={
                    "final": final,
                    "actual_snapshot": actual_snapshot if record.mode == "verify" else {},
                },
            )
        except Exception as exc:  # noqa: BLE001 - 回放失败要落库并如实返回
            await self._replay_store.finish_run(
                record.run_id,
                status="failed",
                matched=0,
                mismatched=0,
                missing=0,
                result={},
                error={"type": type(exc).__name__, "message": str(exc)},
            )

    async def get(self, run_id: str) -> tuple[ReplayRunRecord | None, list[ReplayNodeResult]]:
        record = await self._replay_store.get_run(run_id)
        nodes = await self._replay_store.list_nodes(run_id)
        return record, nodes

    async def compare_now(
        self, left_trace_id: str, right_trace_id: str
    ) -> tuple[list[ReplayNodeResult], dict[str, Any]]:
        left = await self._trace_store.list_trace_events(left_trace_id)
        right = await self._trace_store.list_trace_events(right_trace_id)
        if not left or not right:
            raise ValueError("Trace 不存在")
        return compare_two_traces(left, right)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
