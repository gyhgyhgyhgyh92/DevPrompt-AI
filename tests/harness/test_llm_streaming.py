"""生成流式（2026-11-15）：增量推送到进度出口，完整输出仍由调用方解析。"""

from __future__ import annotations

import types

import pytest
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.harness import llm as llm_mod


class _Probe(BaseModel):
    value: str = "ok"


class _Sink:
    """最小进度出口：记录收到的 ProgressEvent。"""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


class _FakeStreamEvent:
    def __init__(self, delta: str) -> None:
        self.type = "raw_response_event"
        self.data = types.SimpleNamespace(delta=delta)


class _FakeStreamedResult:
    def __init__(self, deltas: list[str]) -> None:
        self._deltas = deltas
        self.final_output = '{"value": "ok"}'
        self.usage = None

    async def stream_events(self):  # type: ignore[no-untyped-def]
        for delta in self._deltas:
            yield _FakeStreamEvent(delta)


async def test_streamed_generate_flushes_tail_to_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """短输出全程快于节流窗口：收尾必须 flush，前端才看得到内容。"""
    monkeypatch.setattr(
        llm_mod.Runner,
        "run_streamed",
        lambda agent, payload, max_turns=1: _FakeStreamedResult(["从", "这里", "开始写"]),
    )
    sink = _Sink()
    token = llm_mod.set_generation_sink(sink)  # type: ignore[arg-type]
    try:
        result = await llm_mod._run_streamed_generate(object(), "user", 5.0)  # type: ignore[arg-type]
    finally:
        llm_mod.reset_generation_sink(token)

    assert result.final_output == '{"value": "ok"}'
    texts = [str(getattr(event, "text", "")) for event in sink.events]
    assert texts, "收尾 flush 必须推送一次增量"
    assert "开始写" in texts[-1]


async def test_generate_without_sink_uses_blocking_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """无推送出口时不走流式（行为与改造前一致）。"""
    called: list[str] = []

    async def fake_run(agent: object, payload: object, timeout: float, **_kw: object) -> object:
        called.append("blocking")

        class _R:
            final_output = '{"value": "ok"}'
            usage = None

        return _R()

    def boom(*_args: object, **_kw: object) -> object:
        called.append("streamed")
        raise AssertionError("无 sink 时不得走流式")

    monkeypatch.setattr(llm_mod, "_run_with_retry", fake_run)
    monkeypatch.setattr(llm_mod.Runner, "run_streamed", boom)

    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        llm_model="model-x",
        llm_base_url="https://api.example.com/x",
        llm_api_key="k-x",
    )
    out = await llm_mod.chat_structured(cfg, _Probe, "sys", "user", purpose="generate")

    assert out.value == "ok"
    assert called == ["blocking"]


async def test_sink_isolated_between_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    """ContextVar 隔离：设置/重置后不该残留到后续调用。"""
    sink = _Sink()
    token = llm_mod.set_generation_sink(sink)  # type: ignore[arg-type]
    assert llm_mod._GENERATION_SINK.get() is sink
    llm_mod.reset_generation_sink(token)
    assert llm_mod._GENERATION_SINK.get() is None
