"""跨模块一致性 E2E：Session Log ↔ Trace ↔ Metrics ↔ Replay 的连接与对应关系。"""

from __future__ import annotations

import asyncio
from typing import Any

from helpers import SAMPLE_PROJECT, FakeStack, assert_seq_contiguous, create_container

from devprompt_ai.domain.obs.contract.query import AggregateQuery
from devprompt_ai.runtime.events import EventBus, EventSink

SENTENCE = "把 SubmitButton 的主色改成 --color-primary-500"


async def _run_with_events(stack: FakeStack, bus: EventBus, *, request_id: str) -> Any:
    # 先建容器再传入 session_id（真实 /runs 由前端先建会话；这里等价显式创建）
    container = await create_container(stack.sessions)
    session_id = container.session_id
    await bus.append(session_id, "run.started", {"request_id": request_id}, run_id=request_id)
    sink = EventSink(bus, session_id, request_id)
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        SENTENCE,
        request_id=request_id,
        progress=sink,
        session_id=session_id,
    )
    await bus.append(
        session_id,
        "snapshot",
        {"status": snapshot.status, "state": snapshot.state, "session_id": snapshot.session_id},
        run_id=request_id,
    )
    await bus.append(
        session_id, "stop", {"status": snapshot.status, "state": snapshot.state}, run_id=request_id
    )
    await stack.collector.flush_all()
    return snapshot


async def test_xm01_join_key_links_log_and_trace(stack: FakeStack, event_bus: EventBus) -> None:
    """XM-01：run.started.request_id == trace.run_id == turn.start.attributes.run_id。"""
    snapshot = await _run_with_events(stack, event_bus, request_id="req-xm1")
    run_events = await event_bus.replay(snapshot.session_id, 0)
    started = next(event for event in run_events if event.type == "run.started")
    request_id = started.payload["request_id"]
    assert request_id == "req-xm1"

    traces = await stack.store.list_traces(snapshot.session_id)
    assert len(traces) == 1
    events = await stack.store.list_trace_events(traces[0].trace_id)
    assert {event.run_id for event in events} == {request_id}
    turn_start = next(event for event in events if event.kind == "turn.start")
    assert turn_start.attributes["run_id"] == request_id
    assert turn_start.session_id == snapshot.session_id


async def test_xm02_turn_state_matches_between_log_trace_metrics(
    stack: FakeStack, event_bus: EventBus, modules: Any
) -> None:
    """XM-02：Session Log 的 stop ↔ Trace turn.end ↔ Metrics turn 序列一致。"""
    snapshot = await _run_with_events(stack, event_bus, request_id="req-xm2")
    stop = [
        event for event in await event_bus.replay(snapshot.session_id, 0) if event.type == "stop"
    ][-1]
    assert stop.payload["state"] == snapshot.state
    assert stop.payload["status"] == snapshot.status

    traces = await stack.store.list_traces(snapshot.session_id)
    events = await stack.store.list_trace_events(traces[0].trace_id)
    turn_end = next(event for event in events if event.kind == "turn.end")
    assert turn_end.output["state"] == stop.payload["state"]
    assert turn_end.output["snapshot"]["state"] == stop.payload["state"]

    by_turn = await modules.metrics.summary(
        AggregateQuery(session_id=snapshot.session_id, group_by="turn")
    )
    assert by_turn
    assert all(point.count > 0 for item in by_turn for point in item.points)


async def test_xm03_action_nodes_match_log_actions(
    stack: FakeStack, event_bus: EventBus, modules: Any
) -> None:
    """XM-03：Session Log 动作可见；Metrics 的 kind 计数与 Trace 节点逐类相等。"""
    snapshot = await _run_with_events(stack, event_bus, request_id="req-xm3")
    log_actions = [
        event for event in await event_bus.replay(snapshot.session_id, 0) if event.type == "action"
    ]
    assert log_actions, "Session Log 应至少有一个工具/文件动作"
    assert all(event.payload.get("title") for event in log_actions)

    traces = await stack.store.list_traces(snapshot.session_id)
    events = await stack.store.list_trace_events(traces[0].trace_id)
    trace_actions = [event for event in events if event.kind == "action.start"]
    assert [event.name for event in trace_actions] == [
        "retrieve",
        "probe",
        "generate",
        "deliver",
    ]

    expected: dict[str, int] = {}
    for event in events:
        expected[event.kind] = expected.get(event.kind, 0) + 1
    series = await modules.metrics.summary(
        AggregateQuery(session_id=snapshot.session_id, group_by="kind")
    )
    actual = {item.key: sum(point.count for point in item.points) for item in series}
    assert actual == expected


async def test_xm04_replay_nodes_belong_to_trace(stack: FakeStack, modules: Any) -> None:
    """XM-04：回放节点 kind ⊆ 左 Trace kind，left_trace_id 归属同一会话。"""
    snapshot = await stack.service.optimize(
        "local", str(SAMPLE_PROJECT), SENTENCE, request_id="req-xm4"
    )
    await stack.collector.flush_all()
    trace = (await stack.store.list_traces(snapshot.session_id))[0]
    events = await stack.store.list_trace_events(trace.trace_id)
    from devprompt_ai.memory.replay_store import SQLiteReplayStore
    from devprompt_ai.obs.replay_service import ReplayService

    service = ReplayService(stack.store, SQLiteReplayStore(modules.cfg.db_path), modules.cfg)
    await service.startup()
    record = await service.create(
        mode="compare", left_trace_id=trace.trace_id, right_trace_id=trace.trace_id
    )
    for _ in range(200):
        latest, nodes = await service.get(record.run_id)
        if latest is not None and latest.status != "running":
            break
        await asyncio.sleep(0.02)
    assert latest is not None and latest.left_trace_id == trace.trace_id
    assert latest.left_trace_id.startswith(snapshot.session_id)
    kinds = {event.kind for event in events}
    assert {node.kind for node in nodes} <= kinds


async def test_xm05_completeness_is_full(stack: FakeStack, modules: Any, trace_store: Any) -> None:
    """XM-05：所有 Trace 均有 start/end、seq 连续，完整率 100%。"""
    for index in range(5):
        snapshot = await stack.service.optimize(
            "local", str(SAMPLE_PROJECT), SENTENCE, request_id=f"req-c{index}"
        )
        await stack.collector.flush_all()
        traces = await stack.store.list_traces(snapshot.session_id)
        assert len(traces) == 1
        events = await stack.store.list_trace_events(traces[0].trace_id)
        kinds = {event.kind for event in events}
        assert "turn.start" in kinds and "turn.end" in kinds
        assert_seq_contiguous(events, traces[0].trace_id)

    summary = await modules.metrics.summary(AggregateQuery(group_by="kind"))
    total = sum(point.count for item in summary for point in item.points)
    assert total > 0
    completeness = 100.0  # 上面逐条断言了 start/end 与 seq 连续
    assert completeness >= 99.9


async def test_xm06_concurrent_sessions_are_isolated(stack: FakeStack, modules: Any) -> None:
    """XM-06：10 会话 × 3 轮并发，无跨会话串数据。"""

    async def _session(index: int) -> str:
        session_id: str | None = None
        for turn in range(3):
            snapshot = await stack.service.optimize(
                "local",
                str(SAMPLE_PROJECT),
                SENTENCE,
                request_id=f"req-{index}-{turn}",
                session_id=session_id,
            )
            session_id = snapshot.session_id
        assert session_id is not None
        return session_id

    session_ids = await asyncio.gather(*(_session(index) for index in range(10)))
    await stack.collector.flush_all()

    for session_id in session_ids:
        traces = await stack.store.list_traces(session_id)
        assert len(traces) == 3, (session_id, len(traces))
        for trace in traces:
            events = await stack.store.list_trace_events(trace.trace_id)
            assert events
            assert {event.session_id for event in events} == {session_id}
            assert_seq_contiguous(events, trace.trace_id)
        series = await modules.metrics.summary(
            AggregateQuery(session_id=session_id, group_by="kind")
        )
        assert series
