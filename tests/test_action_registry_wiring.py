"""接线测试：动作执行器注册表（8 动作分发 + 未注册降级 + 覆盖观测）。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.harness.tool_registry import ToolRegistry
from devprompt_ai.service import ActionHandler, ForgeService
from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols


def _service() -> ForgeService:
    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


def test_all_agent_actions_registered() -> None:
    svc = _service()

    assert set(svc._actions.names()) == {action.value for action in AgentAction}  # noqa: SLF001
    assert svc._actions.overwritten() == frozenset()  # noqa: SLF001


async def test_unregistered_action_warns_and_degrades_to_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    partial: ToolRegistry[ActionHandler] = ToolRegistry()
    for action in AgentAction:
        if action is AgentAction.ABORT:
            continue
        handler = svc._actions.get(action.value)  # noqa: SLF001
        assert handler is not None
        partial.register(action.value, handler)
    svc._actions = partial  # noqa: SLF001
    svc._action_names = frozenset(partial.names())  # noqa: SLF001

    warnings: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "devprompt_ai.service.emit_warning",
        lambda name, **fields: warnings.append((name, fields)),
    )

    session = FlowSession(session_id="s1", user_id="local", state="AGENTIC", data={})
    await svc._sessions.create(session)  # noqa: SLF001

    snapshot = await svc._execute_action_inner(  # noqa: SLF001
        AgentAction.ABORT, session, request_id="r1"
    )

    assert snapshot is not None and snapshot.status == "aborted"
    assert warnings and warnings[0][0] == "agent.action_unregistered"


def test_duplicate_registration_is_observed() -> None:
    """覆盖登记可被装配期观测（防重复注册静默生效）。"""
    registry: ToolRegistry[str] = ToolRegistry()
    registry.register("retrieve", "first")

    assert registry.register("retrieve", "second") is True
    assert registry.overwritten() == frozenset({"retrieve"})
    assert registry.get("retrieve") == "second", "覆盖后以最后注册为准"
