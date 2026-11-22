"""自进化设置段测试（2026-11-22）：保存即生效、回显、关闭旁路。

不落真实库：把 ``write_process_settings`` 换成内存收集器，其余走真实 ``update_settings``。
"""

from __future__ import annotations

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.service import ForgeService
from test_service import (
    FakeDecider,
    FakeGenerator,
    FakeReader,
    FakeRunner,
    FakeStore,
    _symbols,
)


def _svc() -> ForgeService:
    from devprompt_ai.harness.process import SymbolTableProvider

    cfg = AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="http://llm.test/v1",
        llm_api_key="k",
        llm_model="m",
    )
    return ForgeService(
        cfg=cfg,
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


@pytest.fixture(autouse=True)
def _captured_writes(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    written: dict[str, object] = {}

    def _write(values: dict[str, object]) -> None:
        written.update(values)

    monkeypatch.setattr("devprompt_ai.service.write_process_settings", _write)
    return written


async def test_enabling_reflection_swaps_adapter_immediately(
    _captured_writes: dict[str, object],
) -> None:
    svc = _svc()
    assert svc._reflection is None  # 默认关闭：整条链路旁路

    out = await svc.update_settings(
        {"reflection": {"enabled": True, "base_url": "http://127.0.0.1:9999", "top_k": 7}}
    )

    # 适配器已按新配置重建（下一次生成即生效，无需重启）
    assert svc._reflection is not None
    assert out["reflection"] == {
        "enabled": True,
        "base_url": "http://127.0.0.1:9999",
        "top_k": 7,
    }
    # 落库键与 config 回读键一致（重启后仍生效）
    assert _captured_writes["reflection_enabled"] is True
    assert _captured_writes["reflection_base_url"] == "http://127.0.0.1:9999"
    assert _captured_writes["reflection_top_k"] == 7


async def test_disabling_reflection_drops_adapter(_captured_writes: dict[str, object]) -> None:
    svc = _svc()
    await svc.update_settings({"reflection": {"enabled": True}})
    assert svc._reflection is not None

    out = await svc.update_settings({"reflection": {"enabled": False}})

    assert svc._reflection is None
    assert out["reflection"]["enabled"] is False
    assert _captured_writes["reflection_enabled"] is False


async def test_reflection_segment_defaults_reported_when_untouched(
    _captured_writes: dict[str, object],
) -> None:
    svc = _svc()

    out = await svc.update_settings({"reflection": {"top_k": 3}})

    assert out["reflection"]["enabled"] is False  # 未动开关
    assert out["reflection"]["top_k"] == 3
    assert "reflection_enabled" not in _captured_writes  # 只写显式给出的键
