"""MCP 服务端：工具注册与快照渲染，业务仍走 ForgeService。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from devprompt_ai.interfaces.mcp.server import build_server, render_snapshot


def _snapshot(**overrides: Any) -> SimpleNamespace:
    base = {
        "status": "done",
        "state": "DONE",
        "session_id": "s1",
        "questions": [],
        "variant": SimpleNamespace(title="方案", body="正文"),
        "target": None,
        "message": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_render_includes_variant_and_session() -> None:
    text = render_snapshot(_snapshot())
    assert "方案" in text and "正文" in text
    assert "s1" in text


def test_render_includes_questions() -> None:
    text = render_snapshot(_snapshot(questions=[SimpleNamespace(ask="要改哪个页面？")]))
    assert "要改哪个页面？" in text


def test_server_registers_tool_and_delegates_to_service() -> None:
    calls: list[tuple[str, str]] = []

    class FakeService:
        async def optimize(self, user_id: str, project: str, sentence: str, **kwargs: Any):
            calls.append((project, sentence))
            return _snapshot()

    async def _factory() -> Any:
        return FakeService()

    server = build_server(_factory)

    async def _go() -> tuple[list[str], Any]:
        tools = await server.list_tools()
        result = await server.call_tool(
            "optimize_prompt", {"requirement": "改按钮颜色", "project_root": "/proj"}
        )
        return [tool.name for tool in tools], result

    names, result = asyncio.run(_go())
    assert names == ["optimize_prompt"]
    assert calls == [("/proj", "改按钮颜色")]
    assert "方案" in str(result)
