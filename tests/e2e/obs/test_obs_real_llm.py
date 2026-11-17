"""真实大模型 E2E（默认 skip）：成功单轮、两轮会话、认证失败。

运行前置：
1. `~/.devprompt-ai/settings.json` 的 `model_service` 已配置 base_url/model/api_key；
2. 设置 `OBS_E2E_REAL_LLM=1`。
所有调用使用临时 DB，绝不读写用户真实数据库，也不打印密钥。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from helpers import SAMPLE_PROJECT

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.obs.contract.trace import TraceKind
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.obs.replay_service import ReplayService
from devprompt_ai.service import ForgeService, build_default

SENTENCE = "把 SubmitButton、UserTable 和 LoginForm 的主色改成 --color-primary-500"
SENTENCE_2 = "再给 SubmitButton 加一个 hover 状态"


def _read_real_model() -> dict[str, Any] | None:
    if os.environ.get("OBS_E2E_REAL_LLM") != "1":
        return None
    path = Path.home() / ".devprompt-ai" / "settings.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    section = doc.get("model_service")
    if not isinstance(section, dict):
        return None
    if not (section.get("base_url") and section.get("model_id") and section.get("api_key")):
        return None
    return section


REAL = _read_real_model()

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_llm,
    pytest.mark.skipif(REAL is None, reason="需 OBS_E2E_REAL_LLM=1 且 settings.json 已配置模型"),
]


def _cfg(tmp_path: Path, *, api_key: str | None = None) -> AppConfig:
    assert REAL is not None
    return AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=str(tmp_path / "real.db"),
        llm_provider=str(REAL.get("provider", "")),
        llm_base_url=str(REAL["base_url"]),
        llm_api_key=api_key if api_key is not None else str(REAL["api_key"]),
        llm_model=str(REAL["model_id"]),
        api_mode=str(REAL.get("api_mode", "") or ""),
        llm_timeout=120.0,
        llm_generate_timeout=180.0,
        obs_metrics_alert_cooldown_s=0,
    )


async def _wait_replay(service: ReplayService, run_id: str) -> tuple[Any, list[Any]]:
    for _ in range(600):
        record, nodes = await service.get(run_id)
        if record is not None and record.status != "running":
            return record, nodes
        await asyncio.sleep(0.05)
    raise AssertionError("真实 Trace 回放超时")


async def test_rl01_single_turn_success(tmp_path: Path) -> None:
    """RL-01：真实 LLM 单轮成功，Trace 完整且可确定性回放。"""
    cfg = _cfg(tmp_path)
    service: ForgeService = await build_default(cfg)
    snapshot = await service.optimize(
        "local", str(SAMPLE_PROJECT), SENTENCE, request_id="real-rl01"
    )
    assert snapshot.status == "done"
    await service.obs.collector.flush_all()

    traces = await service.obs.trace.list_traces(snapshot.session_id)
    assert len(traces) == 1
    trace_id = traces[0].trace_id
    events = await service.obs.trace_store.list_trace_events(trace_id)
    kinds = {event.kind for event in events}
    for required in (
        TraceKind.TURN_START.value,
        TraceKind.TURN_END.value,
        TraceKind.DECISION.value,
        TraceKind.LLM.value,
        TraceKind.LLM_RESULT.value,
    ):
        assert required in kinds, f"真实链路缺少 {required}"
    llm_events = [event for event in events if event.kind == TraceKind.LLM_RESULT.value]
    assert any(int(event.attributes.get("tokens", 0)) > 0 for event in llm_events)

    replay = ReplayService(
        service.obs.trace_store,
        SQLiteReplayStore(cfg.db_path),
        cfg,
    )
    await replay.startup()
    created = await replay.create(mode="verify", left_trace_id=trace_id)
    record, _nodes = await _wait_replay(replay, created.run_id)
    assert record.status == "matched", record.error


async def test_rl02_two_turn_session(tmp_path: Path) -> None:
    """RL-02：同一会话两轮，Trace 轮次与 Session Log 分段正确。"""
    cfg = _cfg(tmp_path)
    service: ForgeService = await build_default(cfg)
    first = await service.optimize("local", str(SAMPLE_PROJECT), SENTENCE, request_id="real-rl02-1")
    second = await service.optimize(
        "local",
        str(SAMPLE_PROJECT),
        SENTENCE_2,
        request_id="real-rl02-2",
        session_id=first.session_id,
    )
    await service.obs.collector.flush_all()
    traces = await service.obs.trace.list_traces(first.session_id)
    assert len(traces) == 2, f"两轮应有两条 Trace：{traces}"
    assert [trace.turn_index for trace in traces] == [0, 1]
    assert second.session_id == first.session_id


async def test_rl03_auth_failure_is_observable(tmp_path: Path) -> None:
    """RL-03：无效密钥 → 业务失败、Trace failed、Metrics 告警、Replay failed。"""
    cfg = _cfg(tmp_path, api_key="sk-invalid-e2e")
    service: ForgeService = await build_default(cfg)
    with pytest.raises(DevPromptError):
        await service.optimize("local", str(SAMPLE_PROJECT), SENTENCE, request_id="real-rl03")
    await service.obs.collector.flush_all()

    session = service.obs.trace_store
    traces = []
    for candidate in await _all_sessions(service):
        traces = await session.list_traces(candidate)
        if traces:
            break
    assert traces, "失败轮次也必须留下 Trace"
    events = await session.list_trace_events(traces[0].trace_id)
    kinds = {event.kind for event in events}
    assert TraceKind.TURN_START.value in kinds
    assert TraceKind.TURN_END.value in kinds
    turn_end = next(event for event in events if event.kind == TraceKind.TURN_END.value)
    assert turn_end.status == "failed"

    await service.obs.metrics.evaluate(session_id=traces[0].session_id)
    alerts = await service.obs.metrics.alerts()
    assert alerts, "失败链路应至少产生一条告警"

    replay = ReplayService(session, SQLiteReplayStore(cfg.db_path), cfg)
    await replay.startup()
    created = await replay.create(mode="verify", left_trace_id=traces[0].trace_id)
    record, _nodes = await _wait_replay(replay, created.run_id)
    assert record.status == "failed"


async def _all_sessions(service: ForgeService) -> list[str]:
    """从 sessions 存储枚举（真实失败轮次的 session_id 由服务生成）。"""
    store = service._sessions  # noqa: SLF001
    if hasattr(store, "list_recent"):
        items = await store.list_recent("local", limit=10)
        return [item.session_id for item in items]
    return []
