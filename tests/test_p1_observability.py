"""P1 可观测性缺口回归：拒绝率 / Trace 失败分支 / model 维度 / 日志落盘。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import MetricPoint, MetricSeries
from devprompt_ai.domain.obs.metrics.rules import MetricThresholds, evaluate
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.interfaces.api.obs_logs_routes import _read_events
from devprompt_ai.observability.logging import event_log_path, install_file_sink


class _FakeCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, kind: str, name: str, **kwargs: Any) -> str:
        self.events.append({"kind": kind, "name": name, **kwargs})
        return f"e{len(self.events)}"


def test_refusal_rule_flags_failed_llm_responses() -> None:
    series = [
        MetricSeries(
            dimension="kind",
            key="llm.response",
            points=(
                MetricPoint(
                    bucket="all",
                    count=10,
                    failed=3,
                    avg_ms=0,
                    p50_ms=0,
                    p95_ms=0,
                    p99_ms=0,
                    tokens=0,
                ),
            ),
        )
    ]
    drafts = evaluate(
        series,
        MetricThresholds(refusal_rate_warn=0.2),
        scope_kind="session",
        scope_key="s1",
    )
    refusal = [d for d in drafts if d.rule_id == "refusal_rate"]
    assert len(refusal) == 1
    assert refusal[0].metric == "refusal_rate"
    assert refusal[0].observed == pytest.approx(0.3)


def test_model_id_injected_into_llm_nodes(tmp_path: Any) -> None:
    """LLM 节点的 attributes 必须带 model_id，否则 Metrics 的 model 维度恒空。"""
    import asyncio

    from devprompt_ai.memory.trace_store import SQLiteTraceStore

    cfg = AppConfig(_env_file=None, db_path=str(tmp_path / "trace.db"))  # type: ignore[call-arg]
    cfg.llm_model = "deepseek-flash"
    store = SQLiteTraceStore(cfg.db_path)
    collector = TraceCollectorImpl(store, cfg=cfg)

    async def _run() -> None:
        await store.init_schema()
        await collector.start_turn(
            session_id="s1", turn_id="t1", turn_index=0, sentence="x", project_root="."
        )
        await collector.record("llm.request", "generate_single", attributes={"purpose": "generate"})
        cfg.llm_model = "kimi-k3"  # 热切换后新节点跟随
        await collector.record("llm.response", "generate_single", attributes={})
        await collector.flush()
        events = await store.list_trace_events("s1:0:turn")
        models = [event.attributes.get("model_id") for event in events]
        assert "deepseek-flash" in models
        assert "kimi-k3" in models

    asyncio.run(_run())


def test_event_log_roundtrip(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import devprompt_ai.observability.logging as logmod

    log_dir = str(tmp_path / "logs")
    monkeypatch.setattr(logmod, "_FILE_SINK_INSTALLED", False)
    # 移除前面测试可能挂到全局 logger 的 handler，避免串场
    for handler in list(logmod.logger.handlers):
        if isinstance(handler, __import__("logging").handlers.RotatingFileHandler):
            logmod.logger.removeHandler(handler)
    install_file_sink(log_dir)
    from devprompt_ai.observability.logging import emit

    emit("agent.step", action="probe", request_id="r-test")
    rows = _read_events(event_log_path(log_dir), event="agent.step", request_id="r-test", limit=10)
    assert len(rows) >= 1
    assert rows[0]["action"] == "probe"
    assert rows[0]["request_id"] == "r-test"
