"""Trace 模块独立功能 E2E：采集、存储、查询、开关、保留期与 fail-open。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from helpers import (
    SAMPLE_PROJECT,
    FakeStack,
    assert_seq_contiguous,
    make_event,
    seed_trace,
    symbols,
)

from conftest import patch_obs
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import TraceQuery
from devprompt_ai.domain.obs.contract.trace import TraceKind
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.registry import build_obs_modules


async def test_tr01_collects_full_chain(stack: FakeStack) -> None:
    """TR-01：一次 fake 运行产出完整调用链，seq 连续、父子可组装。"""
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-tr01",
    )
    await stack.collector.flush_all()
    assert snapshot.status == "done"

    traces = await stack.store.list_traces(snapshot.session_id)  # type: ignore[attr-defined]
    assert len(traces) == 1
    events = await stack.store.list_trace_events(traces[0].trace_id)  # type: ignore[attr-defined]
    kinds = {event.kind for event in events}
    for required in (
        TraceKind.TURN_START.value,
        TraceKind.TURN_END.value,
        TraceKind.ACTION_START.value,
        TraceKind.ACTION_END.value,
        TraceKind.DECISION.value,
        TraceKind.DECISION_RESULT.value,
        TraceKind.FILE.value,
        TraceKind.TOOL.value,
        TraceKind.LLM.value,
        TraceKind.LLM_RESULT.value,
    ):
        assert required in kinds, f"缺少 {required}；实际 {sorted(kinds)}"
    assert_seq_contiguous(events, traces[0].trace_id)
    assert any(event.parent_id for event in events), "至少一个事件应有父节点"


async def test_tr02_query_tree_and_detail(modules: Any, trace_store: SQLiteTraceStore) -> None:
    """TR-02：列表/事件分页/调用树/详情与 kind 筛选可用。"""
    events = seed_trace(
        trace_store,
        trace_id="s1:0:req",
        session_id="s1",
        turn_index=0,
        run_id="req",
        count=30,
        kinds=["tool.result", "llm.response", "action.end"],
    )
    await trace_store.append_events(events)

    traces = await modules.trace.list_traces("s1")
    assert traces and traces[0].event_count == 30

    page, has_more, _cursor = await modules.trace.query_events(
        TraceQuery(session_id="s1", kind="tool.result", limit=5)
    )
    assert has_more is True
    assert len(page) == 5
    assert all(item["kind"] == "tool.result" for item in page)

    tree = await modules.trace.trace_tree("s1:0:req", full=True)
    assert tree and tree[0]["kind"] == "turn.start"
    assert "input" in tree[0]

    event = await modules.trace.get_event(events[0].event_id)
    assert event is not None and event.kind == "turn.start"


async def test_tr03_secrets_are_masked(
    collector: TraceCollectorImpl, trace_store: SQLiteTraceStore
) -> None:
    """TR-03：密钥字段落库前掩码，普通字段保留明文。"""
    await collector.start_turn(
        session_id="mask",
        turn_id="t1",
        turn_index=0,
        sentence="s",
        project_root=".",
    )
    await collector.record(
        TraceKind.TOOL.value,
        "command",
        input={
            "api_key": "sk-secret",
            "nested": {"authorization": "Bearer token", "safe": "ok"},
            "command": "rg x",
        },
    )
    await collector.end_turn(state="DONE")
    await collector.flush_all()

    events = await trace_store.list_trace_events("mask:0:turn")
    assert len(events) == 3
    payload = next(event for event in events if event.kind == TraceKind.TOOL.value).input
    assert payload["api_key"] == "***"
    assert payload["nested"]["authorization"] == "***"
    assert payload["nested"]["safe"] == "ok"
    assert payload["command"] == "rg x"


async def test_tr04_multi_turn_pagination_is_turn_major(
    modules: Any, trace_store: SQLiteTraceStore
) -> None:
    """TR-04：同一会话两轮 Trace，台账按轮次升序且分页无重漏。"""
    for turn in range(2):
        events = seed_trace(
            trace_store,
            trace_id=f"s1:{turn}:req{turn}",
            session_id="s1",
            turn_index=turn,
            run_id=f"req{turn}",
            count=20,
        )
        await trace_store.append_events(events)

    page, has_more, cursor = await modules.trace.query_events(TraceQuery(session_id="s1", limit=20))
    turn_indexes = [item["turn_index"] for item in page]
    assert turn_indexes == sorted(turn_indexes)
    assert len(page) == 20 and has_more is True and cursor == 20

    rest, has_more2, _ = await modules.trace.query_events(
        TraceQuery(session_id="s1", cursor=cursor, limit=200)
    )
    combined = page + rest
    assert len(combined) == 40 and has_more2 is False
    assert [item["turn_index"] for item in combined] == sorted(
        item["turn_index"] for item in combined
    )
    event_ids = [item["event_id"] for item in combined]
    assert len(set(event_ids)) == 40, "分页不得重复或漏读"


async def test_tr05_disabled_module_blocks_api_and_collection(
    tmp_path: Any, api_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TR-05：模块关闭时 API 返回 6004，采集器不落库。"""
    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=str(tmp_path / "off.db"),
        obs_trace_enabled=False,
        obs_metrics_enabled=True,
        obs_replay_enabled=True,
    )
    modules = build_obs_modules(cfg)
    await modules.startup()
    patch_obs(monkeypatch, modules)

    resp = await api_client.get("/api/v1/obs/trace/sessions/s1/traces")
    assert resp.status_code == 404
    assert resp.json()["code"] == 6004

    assert (
        await modules.collector.start_turn(
            session_id="s1", turn_id="t", turn_index=0, sentence="s", project_root="."
        )
        == ""
    )
    store = SQLiteTraceStore(cfg.db_path)
    assert await store.list_traces("s1") == []


async def test_tr06_retention_cleanup(trace_store: SQLiteTraceStore) -> None:
    """TR-06：retention_days 清理旧事件；0 表示不清理。"""
    import dataclasses

    old = dataclasses.replace(
        make_event(1, TraceKind.ACTION_END.value),
        started_at="2020-01-01T00:00:00.000Z",
    )
    # 新事件用当前时间：make_event 的固定时间会随日期推移被当成过期（时间炸弹）。
    fresh = dataclasses.replace(
        make_event(2, TraceKind.ACTION_END.value),
        started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )
    await trace_store.append_events([old, fresh])

    assert await trace_store.cleanup_expired(0) == 0
    assert len(await trace_store.list_trace_events(old.trace_id)) == 2
    removed = await trace_store.cleanup_expired(1)
    assert removed == 1
    assert [event.seq for event in await trace_store.list_trace_events(old.trace_id)] == [2]


async def test_tr07_write_failure_is_fail_open(
    cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TR-07：轮次收尾写失败不阻断业务（buffer 足够大，失败只发生在 end_turn）。"""
    from helpers import build_stack

    from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl

    collector = TraceCollectorImpl(SQLiteTraceStore(cfg.db_path), buffer_size=10000)
    stack = build_stack(cfg, collector)

    async def _boom(_events: Any) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(collector._store, "append_events", _boom)  # noqa: SLF001
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-fail",
    )
    await collector.flush_all()

    assert snapshot.status == "done", "观测失败不得阻断业务"
    assert collector._partial, "写失败后应标记 partial"  # noqa: SLF001


async def test_tr08_symbols_recorded_when_no_override(cfg: AppConfig, modules: Any) -> None:
    """TR-08：无 symbols_override 时符号表调用也应被录制（Replay 前提）。"""
    from helpers import build_stack

    stack = build_stack(cfg, modules.collector, record_symbols=True)
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-sym",
    )
    await stack.collector.flush_all()
    events = await stack.store.list_trace_events(  # type: ignore[attr-defined]
        (await stack.store.list_traces(snapshot.session_id))[0].trace_id  # type: ignore[attr-defined]
    )
    assert TraceKind.SYMBOLS.value in {event.kind for event in events}
    assert symbols()  # 固定夹具非空


async def test_tr09_llm_tokens_follow_usage_aggregate(cfg: AppConfig, modules: Any) -> None:
    """TR-09（D-06）：LLM 节点 tokens 取本次调用的请求级聚合差值。"""
    from helpers import FakeGenerator, build_stack

    from devprompt_ai.harness.llm import _record_usage

    class UsageGenerator(FakeGenerator):
        async def generate_single(self, ctx: Any, locale: str = "zh-CN", *, fallback: bool = False):  # type: ignore[no-untyped-def]
            _record_usage({"total_tokens": 321, "prompt_tokens": 300, "completion_tokens": 21})
            return await super().generate_single(ctx, locale, fallback=fallback)

    stack = build_stack(cfg, modules.collector, generator=UsageGenerator())
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-tokens",
    )
    await stack.collector.flush_all()
    events = await stack.store.list_trace_events(  # type: ignore[attr-defined]
        (await stack.store.list_traces(snapshot.session_id))[0].trace_id  # type: ignore[attr-defined]
    )
    llm_results = [event for event in events if event.kind == TraceKind.LLM_RESULT.value]
    assert llm_results and llm_results[0].attributes["tokens"] == 321
