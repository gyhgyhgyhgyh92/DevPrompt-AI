"""韧性/异常 E2E：取消、长会话、重启与写失败。"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import pytest
from helpers import SAMPLE_PROJECT, FakeGenerator, FakeStack, build_stack, percentile

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import AggregateQuery
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.obs.registry import build_obs_modules
from devprompt_ai.obs.replay_service import ReplayService

SENTENCE = "把 SubmitButton 的主色改成 --color-primary-500"


class SlowGenerator(FakeGenerator):
    """生成阶段阻塞，用于模拟用户取消。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_single(self, *args: Any, **kwargs: Any) -> Any:
        self.started.set()
        await self.release.wait()
        return await super().generate_single(*args, **kwargs)


async def test_ab03_cancel_mid_run_is_recorded(cfg: AppConfig, modules: Any) -> None:
    """AB-03：生成阶段取消 → 业务取消、Trace 有收尾、回放 graceful failed。"""
    slow = SlowGenerator()
    stack = build_stack(cfg, modules.collector, generator=slow)
    task = asyncio.create_task(
        stack.service.optimize("local", str(SAMPLE_PROJECT), SENTENCE, request_id="req-cancel")
    )
    await asyncio.wait_for(slow.started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stack.collector.flush_all()

    session = next(iter(stack.sessions.items.values()))
    traces = await stack.store.list_traces(session.session_id)
    assert len(traces) == 1
    events = await stack.store.list_trace_events(traces[0].trace_id)
    kinds = [event.kind for event in events]
    assert "turn.start" in kinds
    assert "turn.end" in kinds, "取消也必须收尾，否则回放/指标无终止信号"
    turn_end = next(event for event in events if event.kind == "turn.end")
    assert turn_end.status == "failed"

    service = ReplayService(stack.store, SQLiteReplayStore(cfg.db_path), cfg)
    await service.startup()
    created = await service.create(mode="verify", left_trace_id=traces[0].trace_id)
    for _ in range(200):
        record, _nodes = await service.get(created.run_id)
        if record is not None and record.status != "running":
            break
        await asyncio.sleep(0.02)
    assert record is not None and record.status in {"failed", "diverged", "matched"}


async def test_ab05_long_session_50_turns(stack: FakeStack, modules: Any) -> None:
    """AB-05：50 轮长会话，Trace 数量正确、查询有界、DB 增长可观察。"""
    session_id: str | None = None
    started = time.perf_counter()
    for turn in range(50):
        snapshot = await stack.service.optimize(
            "local",
            str(SAMPLE_PROJECT),
            SENTENCE,
            request_id=f"req-long-{turn}",
            session_id=session_id,
        )
        session_id = snapshot.session_id
    elapsed = time.perf_counter() - started
    await stack.collector.flush_all()
    assert session_id is not None

    traces = await stack.store.list_traces(session_id)
    assert len(traces) == 50
    total_events = sum(trace.event_count for trace in traces)
    assert total_events > 200

    timings: list[float] = []
    for _ in range(10):
        tick = time.perf_counter()
        await modules.metrics.summary(AggregateQuery(session_id=session_id, group_by="kind"))
        timings.append((time.perf_counter() - tick) * 1000)
    assert percentile(timings, 95) <= 500, f"长会话查询 P95 超限：{timings}"
    size = await asyncio.to_thread(os.path.getsize, stack.store._db_path)  # noqa: SLF001
    assert size > 0
    assert elapsed < 120, f"50 轮 fake 运行耗时异常：{elapsed:.1f}s"


async def test_ab07_restart_keeps_data_readable(cfg: AppConfig, modules: Any) -> None:
    """AB-07：同一 DB 重启后 Trace/Metrics 数据仍可读。"""
    stack = build_stack(cfg, modules.collector)
    snapshot = await stack.service.optimize(
        "local", str(SAMPLE_PROJECT), SENTENCE, request_id="req-restart"
    )
    await stack.collector.flush_all()

    reopened = build_obs_modules(cfg)
    await reopened.startup()
    traces = await reopened.trace.list_traces(snapshot.session_id)
    assert len(traces) == 1
    series = await reopened.metrics.summary(
        AggregateQuery(session_id=snapshot.session_id, group_by="kind")
    )
    assert series


async def test_ab06_trace_write_failure_keeps_business(
    stack: FakeStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AB-06（D-02）：Trace 写失败 fail-open（业务成功、错误不冒泡）。"""

    async def _boom(_events: Any) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(stack.collector._store, "append_events", _boom)  # noqa: SLF001
    snapshot = await stack.service.optimize(
        "local", str(SAMPLE_PROJECT), SENTENCE, request_id="req-ab06"
    )
    await stack.collector.flush_all()
    assert snapshot.status == "done"
    assert stack.collector._partial  # noqa: SLF001
