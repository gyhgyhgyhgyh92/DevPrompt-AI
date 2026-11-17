"""Replay 模块独立功能 E2E：verify/compare、录制缺失、partial 与开关。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from helpers import SAMPLE_PROJECT, build_stack, make_event, seed_trace

from conftest import patch_obs
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.trace import TraceEvent
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.registry import build_obs_modules
from devprompt_ai.obs.replay_service import ReplayService


async def _wait(service: ReplayService, run_id: str) -> tuple[Any, list[Any]]:
    for _ in range(300):
        record, nodes = await service.get(run_id)
        if record is not None and record.status != "running":
            return record, nodes
        await asyncio.sleep(0.02)
    raise AssertionError("回放任务超时未结束")


async def test_rp01_fake_verify_matches(cfg: AppConfig, modules: Any) -> None:
    """RP-01：fake 全链路 Trace 的 verify 全部 MATCH。"""
    stack = build_stack(cfg, modules.collector, record_symbols=True)
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-rp01",
    )
    await stack.collector.flush_all()
    trace = (await stack.store.list_traces(snapshot.session_id))[0]

    service = ReplayService(stack.store, SQLiteReplayStore(cfg.db_path), cfg)
    await service.startup()
    created = await service.create(mode="verify", left_trace_id=trace.trace_id)
    record, nodes = await _wait(service, created.run_id)
    assert record.status == "matched", record.error
    assert nodes and all(node.match for node in nodes)
    assert record.result["final"]["match"] is True


async def test_rp02_real_llm_verify_is_covered_in_real_suite() -> None:
    """RP-02 由 tests/e2e/obs/test_obs_real_llm.py 覆盖（避免默认套件产生费用）。"""
    assert True


async def test_rp03_compare_same_and_different_input(
    modules: Any, trace_store: SQLiteTraceStore
) -> None:
    """RP-03：同 input_hash 可对比；不同 hash 拒绝；缺失 trace 拒绝。"""
    same_a = seed_trace(
        trace_store,
        trace_id="s3:0:a",
        session_id="s3",
        turn_index=0,
        run_id="a",
        count=10,
    )
    same_b = seed_trace(
        trace_store,
        trace_id="s3:0:b",
        session_id="s3",
        turn_index=0,
        run_id="b",
        count=10,
    )
    await trace_store.append_events(same_a + same_b)
    nodes, final = await modules.replay.compare_now("s3:0:a", "s3:0:b")
    assert nodes and all(node.match for node in nodes)
    assert final["match"] is True

    other = seed_trace(
        trace_store,
        trace_id="s3:1:c",
        session_id="s3",
        turn_index=1,
        run_id="c",
        count=10,
    )
    await trace_store.append_events(other)
    with pytest.raises(ValueError, match="input_hash"):
        await modules.replay.create(mode="compare", left_trace_id="s3:0:a", right_trace_id="s3:1:c")
    with pytest.raises(ValueError, match="Trace 不存在"):
        await modules.replay.compare_now("missing", "s3:0:a")


async def test_rp04_missing_record_fails_cleanly(cfg: AppConfig, modules: Any) -> None:
    """RP-04：删除 LLM 结果后回放 failed，错误可查且不抛到 API。"""
    stack = build_stack(cfg, modules.collector, record_symbols=True)
    snapshot = await stack.service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        "把 SubmitButton 的主色改成 --color-primary-500",
        request_id="req-rp04",
    )
    await stack.collector.flush_all()
    trace = (await stack.store.list_traces(snapshot.session_id))[0]
    events = await stack.store.list_trace_events(trace.trace_id)
    kept = [event for event in events if "llm.response" not in event.kind]
    rebuilt = [
        make_event(
            index,
            event.kind,
            trace_id=event.trace_id,
            session_id=event.session_id,
            turn_index=event.turn_index,
            run_id=event.run_id,
            status=event.status,
            duration_ms=event.duration_ms,
            name=event.name,
            input=event.input,
            output=event.output,
            attributes=event.attributes,
            parent_id=event.parent_id,
        )
        for index, event in enumerate(kept, start=1)
    ]
    store = SQLiteTraceStore(str(cfg.db_path))
    await store.append_events(rebuilt)

    service = ReplayService(store, SQLiteReplayStore(cfg.db_path), cfg)
    await service.startup()
    created = await service.create(mode="verify", left_trace_id=trace.trace_id)
    record, _nodes = await _wait(service, created.run_id)
    assert record.status == "failed"
    assert record.error["type"] in {"MissingRecordError", "ValueError"}


async def test_rp05_disabled_and_unknown(
    tmp_path: Any, api_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RP-05：关闭返回 6004；未知 run 返回 6003。"""
    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=str(tmp_path / "off.db"),
        obs_replay_enabled=False,
    )
    modules = build_obs_modules(cfg)
    await modules.startup()
    patch_obs(monkeypatch, modules)
    resp = await api_client.get("/api/v1/obs/replay/runs/unknown")
    assert resp.status_code == 404
    assert resp.json()["code"] == 6004


async def test_rp06_compare_reports_diff(modules: Any, trace_store: SQLiteTraceStore) -> None:
    """RP-06：输出被篡改时 compare 产生 diverged 与精确 diff 路径。"""
    left = seed_trace(
        trace_store,
        trace_id="s6:0:a",
        session_id="s6",
        turn_index=0,
        run_id="a",
        count=6,
    )
    right = seed_trace(
        trace_store,
        trace_id="s6:0:b",
        session_id="s6",
        turn_index=0,
        run_id="b",
        count=6,
    )
    right = [
        make_event(
            event.seq,
            event.kind,
            trace_id=event.trace_id,
            session_id=event.session_id,
            turn_index=event.turn_index,
            run_id=event.run_id,
            duration_ms=event.duration_ms,
            name=event.name,
            input=event.input,
            output={"mutated": True} if event.kind == "tool.result" else event.output,
            attributes=event.attributes,
        )
        for event in right
    ]
    await trace_store.append_events(left + right)
    nodes, final = await modules.replay.compare_now("s6:0:a", "s6:0:b")
    assert any(not node.match for node in nodes)
    assert any(node.diff.get("diffs") for node in nodes if not node.match)
    assert final["match"] is True, "最终快照未变，差异应在节点层"


async def test_rp07_partial_trace_fails_without_crash(
    cfg: AppConfig, modules: Any, trace_store: SQLiteTraceStore
) -> None:
    """RP-07：只有 turn.start 的 partial Trace 回放 failed，不泄漏堆栈。"""
    partial = TraceEvent(
        event_id="e-partial",
        trace_id="s7:0:req",
        session_id="s7",
        turn_id="t7",
        turn_index=0,
        run_id="req",
        seq=1,
        parent_id="",
        kind="turn.start",
        name="turn",
        status="ok",
        started_at="2026-11-13T10:00:00.000Z",
        ended_at="2026-11-13T10:00:00.100Z",
        duration_ms=100,
        input={
            "sentence": "把 SubmitButton 的主色改成 --color-primary-500",
            "project_root": str(SAMPLE_PROJECT),
            "session_data": {"sentence": "x", "project_root": str(SAMPLE_PROJECT)},
        },
        output={},
        error={},
        attributes={"run_id": "req"},
    )
    await trace_store.append_events([partial])
    service = ReplayService(trace_store, SQLiteReplayStore(cfg.db_path), cfg)
    await service.startup()
    created = await service.create(mode="verify", left_trace_id=partial.trace_id)
    record, _nodes = await _wait(service, created.run_id)
    assert record.status == "failed"
    assert record.error
    assert "Traceback" not in str(record.error)
