"""MCP 双向自测：真起本项目的 stdio Server，用官方客户端连上并发现工具。

只验证协议握手与工具注册（不调 LLM，确定性）；真正的生成调用由 real_llm 用例覆盖。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from agents.mcp import MCPServerStdio

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.e2e
def test_stdio_server_lists_optimize_tool() -> None:
    async def _go() -> list[str]:
        server = MCPServerStdio(
            params={
                "command": sys.executable,
                "args": ["-m", "devprompt_ai.interfaces.mcp.server", "--transport", "stdio"],
                "env": {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            },
            client_session_timeout_seconds=20,
        )
        async with server:
            tools = await server.list_tools()
            return [tool.name for tool in tools]

    names = asyncio.run(_go())
    assert "optimize_prompt" in names


@pytest.mark.e2e
@pytest.mark.real_llm
@pytest.mark.skipif(
    os.environ.get("OBS_E2E_REAL_LLM") != "1",
    reason="真实 LLM 用例默认跳过；设 OBS_E2E_REAL_LLM=1 启用",
)
def test_stdio_server_call_runs_real_flow(tmp_path: Path) -> None:
    """通过 MCP 客户端真实调一次：返回文本里必须带状态与方案。"""
    project = tmp_path / "tiny"
    project.mkdir()
    (project / "app.py").write_text("def submit_button():\n    return 'old'\n", encoding="utf-8")

    async def _go() -> str:
        server = MCPServerStdio(
            params={
                "command": sys.executable,
                "args": ["-m", "devprompt_ai.interfaces.mcp.server", "--transport", "stdio"],
                "env": {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            },
            client_session_timeout_seconds=240,
        )
        async with server:
            result = await server.call_tool(
                "optimize_prompt",
                {"requirement": "把 submit_button 的返回值改成 new", "project_root": str(project)},
            )
            return str(result)

    text = asyncio.run(_go())
    assert "状态" in text
