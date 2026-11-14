"""可观测性四模块 E2E 夹具：临时库、真实采集器、fake 端口与 ASGI 客户端。"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import FakeStack, build_stack

from devprompt_ai.config import AppConfig
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.interfaces.api import obs_common, runtime_routes
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.registry import ObsModules, build_obs_modules
from devprompt_ai.runtime.events import EventBus


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """整个目录统一打 e2e 标记（conftest 的 pytestmark 不会继承到测试模块）。"""
    del config
    for item in items:
        if "e2e" in item.path.parts and "obs" in item.path.parts:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    """隔离配置：临时 DB、三模块全开、告警冷却归零便于断言。"""
    return AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=str(tmp_path / "obs.db"),
        obs_metrics_alert_cooldown_s=0,
    )


@pytest.fixture
async def modules(cfg: AppConfig) -> ObsModules:
    built = build_obs_modules(cfg)
    await built.startup()
    return built


@pytest.fixture
def trace_store(cfg: AppConfig) -> SQLiteTraceStore:
    return SQLiteTraceStore(cfg.db_path)


@pytest.fixture
async def collector(modules: ObsModules) -> TraceCollectorImpl:
    return modules.collector


@pytest.fixture
async def stack(cfg: AppConfig, collector: TraceCollectorImpl) -> FakeStack:
    return build_stack(cfg, collector)


@pytest.fixture
async def event_bus(tmp_path: Path) -> EventBus:
    store = SQLiteEventStore(str(tmp_path / "obs.db"))
    await store.init_schema()
    return EventBus(store)


@pytest.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class _FakeService:
    def __init__(self, modules: ObsModules) -> None:
        self.obs = modules
        self.config = modules.cfg


class _FakeBundle:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus


def patch_obs(monkeypatch: pytest.MonkeyPatch, modules: ObsModules) -> None:
    """让 obs 路由复用测试模块集合（不触发真实 build_default）。"""

    async def _fake_service() -> _FakeService:
        return _FakeService(modules)

    monkeypatch.setattr(obs_common, "get_service", _fake_service)


def patch_runtime(monkeypatch: pytest.MonkeyPatch, modules: ObsModules, bus: EventBus) -> None:
    """让 `/events` 路由直接读测试 EventBus。"""

    async def _fake_service() -> Any:
        return _FakeService(modules)

    async def _fake_runtime(*_args: Any, **_kwargs: Any) -> _FakeBundle:
        return _FakeBundle(bus)

    monkeypatch.setattr(runtime_routes, "get_service", _fake_service)
    monkeypatch.setattr(runtime_routes, "get_runtime", _fake_runtime)
