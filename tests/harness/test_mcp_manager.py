"""MCP 客户端：配置校验、传输分流、白名单、失败降级。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from devprompt_ai.domain.mcp.models import McpServerConfig
from devprompt_ai.harness.mcp.filters import build_tool_filter
from devprompt_ai.harness.mcp.manager import build_server, probe_server
from devprompt_ai.harness.mcp.runtime import get_servers, parse_servers


def test_stdio_requires_command_and_rejects_shell_meta() -> None:
    with pytest.raises(ValidationError):
        McpServerConfig(name="x", transport="stdio", command="")
    with pytest.raises(ValidationError):
        McpServerConfig(name="x", transport="stdio", command="rm -rf / && echo hi")


def test_stdio_env_merges_parent_process() -> None:
    """只填业务变量时仍要保留 PATH 等基础变量，否则命令可能根本找不到。"""
    config = McpServerConfig(
        name="x", transport="stdio", command="python", env={"ONLY_MINE": "1"}
    )
    server = build_server(config)
    env = server.params.env
    assert env["ONLY_MINE"] == "1"
    assert "PATH" in env or "Path" in env


def test_remote_requires_http_url() -> None:
    with pytest.raises(ValidationError):
        McpServerConfig(name="x", transport="sse", url="ftp://nope")
    assert McpServerConfig(name="x", transport="sse", url="https://a/b").transport == "sse"


def test_public_view_masks_env_and_headers() -> None:
    config = McpServerConfig(
        name="x",
        transport="sse",
        url="https://a/mcp",
        env={"API_KEY": "secret", "PLAIN": "ok"},
        headers={"Authorization": "Bearer t"},
    )
    view = config.public_view()
    assert view["env"]["API_KEY"] == "••••••"
    assert view["env"]["PLAIN"] == "ok"
    assert view["headers"]["Authorization"] == "••••••"


def test_empty_allowlist_means_no_filter() -> None:
    assert build_tool_filter([]) is None
    filtered = build_tool_filter(["read", "write"])
    assert filtered is not None


def test_build_server_per_transport() -> None:
    from agents.mcp import MCPServerSse, MCPServerStdio, MCPServerStreamableHttp

    stdio = build_server(McpServerConfig(name="a", command="python"))
    sse = build_server(McpServerConfig(name="b", transport="sse", url="https://a/sse"))
    http = build_server(
        McpServerConfig(name="c", transport="streamable-http", url="https://a/mcp")
    )
    assert isinstance(stdio, MCPServerStdio)
    assert isinstance(sse, MCPServerSse)
    assert isinstance(http, MCPServerStreamableHttp)


def test_disabled_configs_yield_no_servers() -> None:
    async def _go() -> list[Any]:
        return await get_servers(
            [McpServerConfig(name="off", command="python", enabled=False)], enabled=True
        )

    assert asyncio.run(_go()) == []
    assert asyncio.run(get_servers([McpServerConfig(name="a", command="python")], enabled=False)) == []


def test_parse_servers_skips_invalid() -> None:
    parsed = parse_servers(
        [
            {"name": "good", "command": "python", "enabled": True},
            {"name": "bad", "command": "a && b"},
        ]
    )
    assert [item.name for item in parsed] == ["good"]


def test_probe_reports_failure_without_raising() -> None:
    result = asyncio.run(
        probe_server(
            McpServerConfig(name="missing", command="definitely-not-a-real-command-xyz"),
            timeout_s=2.0,
        )
    )
    assert result["ok"] is False
    assert result["error"]
