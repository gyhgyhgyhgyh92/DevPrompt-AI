"""Trace 存储：写入、查询、聚合与保留期清理。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.obs.contract.query import AggregateQuery, TraceQuery
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceKind
from devprompt_ai.memory.trace_store import SQLiteTraceStore


def _event(
    seq: int, kind: str, *, duration: int = 10, status: str = "ok", started_at: str = ""
) -> TraceEvent:
    return TraceEvent(
        event_id=f"e{seq}",
        trace_id="s1:0:req",
        session_id="s1",
        turn_id="turn1",
        turn_index=0,
        run_id="r1",
        seq=seq,
        parent_id="",
        kind=kind,
        name=kind,
        status=status,
        started_at=started_at or f"2026-11-12T10:00:{seq:02d}.000Z",
        ended_at=f"2026-11-12T10:00:{seq:02d}.500Z",
        duration_ms=duration,
        input={"request": seq},
        output={"response": seq},
        attributes={"model_id": "m1", "tokens": 100, "input_hash": "hash1"},
    )


async def test_trace_store_roundtrip_and_aggregate(tmp_path: Any) -> None:
    store = SQLiteTraceStore(str(tmp_path / "obs.db"))
    await store.init_schema()
    await store.append_events(
        [_event(1, TraceKind.ACTION_END.value), _event(2, TraceKind.LLM_RESULT.value)]
    )

    summaries = await store.list_traces("s1")
    assert len(summaries) == 1
    assert summaries[0].event_count == 2
    assert summaries[0].input_hash == ""

    events, has_more, cursor = await store.query_events(TraceQuery(session_id="s1", limit=1))
    assert len(events) == 1 and has_more is True and cursor == 1
    assert (await store.get_event("e1")).seq == 1

    series = await store.aggregate(AggregateQuery(session_id="s1", group_by="kind"))
    assert {item.key for item in series} == {"action.end", "llm.response"}
    assert all(item.points[0].tokens == 100 for item in series)

    # input_hash 只从 turn.start 读取：补一条 start 后应能取到
    await store.append_events([_event(0, TraceKind.TURN_START.value)])
    summaries = await store.list_traces("s1")
    assert summaries[0].input_hash == "hash1"


async def test_trace_store_query_is_turn_major_and_paged(tmp_path: Any) -> None:
    """D-01：会话级查询按轮次升序，offset 游标跨 trace 分页无重漏。"""
    import dataclasses

    store = SQLiteTraceStore(str(tmp_path / "obs.db"))
    await store.init_schema()
    base = _event(1, TraceKind.ACTION_END.value)
    events = [
        dataclasses.replace(
            base,
            event_id=f"e{turn}-{seq}",
            trace_id=f"s1:{turn}:req{turn}",
            turn_index=turn,
            run_id=f"r{turn}",
            seq=seq,
        )
        for turn in range(2)
        for seq in range(1, 4)
    ]
    await store.append_events(events)

    page, has_more, cursor = await store.query_events(TraceQuery(session_id="s1", limit=2))
    assert [event.turn_index for event in page] == [0, 0]
    assert has_more is True and cursor == 2

    rest, has_more2, _ = await store.query_events(
        TraceQuery(session_id="s1", cursor=cursor, limit=10)
    )
    combined = page + rest
    assert has_more2 is False
    assert [event.turn_index for event in combined] == [0, 0, 0, 1, 1, 1]
    assert len({event.event_id for event in combined}) == 6


async def test_trace_store_cleanup_expired(tmp_path: Any) -> None:
    store = SQLiteTraceStore(str(tmp_path / "obs.db"))
    await store.init_schema()
    await store.append_events(
        [_event(1, TraceKind.ACTION_END.value, started_at="2020-01-01T00:00:00.000Z")]
    )

    removed = await store.cleanup_expired(1)

    assert removed == 1
