"""MCP 客户端管理（2026-11-21）：配置 → SDK Server → 统一连接与清理。

刻意不自己实现协议：连接、工具发现、调用、结果回喂、重试全部由
`agents.mcp` 完成；本模块只负责「按配置造对象、连、断、报状态」。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from agents.mcp import (
    MCPServerManager,
    MCPServerSse,
    MCPServerSseParams,
    MCPServerStdio,
    MCPServerStdioParams,
    MCPServerStreamableHttp,
    MCPServerStreamableHttpParams,
)

from devprompt_ai.domain.mcp.models import McpServerConfig
from devprompt_ai.harness.mcp.approval import approve_tool_call
from devprompt_ai.harness.mcp.filters import build_tool_filter
from devprompt_ai.observability.logging import emit

logger = logging.getLogger(__name__)


def _server_key(config: McpServerConfig) -> str:
    return config.id or config.name


def build_server(config: McpServerConfig, *, session_timeout_s: float = 30.0) -> Any:
    """按传输方式构造 SDK Server；工具白名单与审批回调统一挂上。"""
    common: dict[str, Any] = {
        "cache_tools_list": True,
        "name": config.name,
        "client_session_timeout_seconds": session_timeout_s,
        "tool_filter": build_tool_filter(config.tool_allowlist),
        "require_approval": approve_tool_call,
    }
    if config.transport == "stdio":
        # env 与父进程合并而非替换（2026-11-21）：只填业务变量时，PATH/SystemRoot
        # 等基础变量仍需存在，否则 Windows 上连命令都找不到。用户配置优先。
        # SDK 的 params.env 是 NotRequired：不能传 None，只能省略该键。
        params: MCPServerStdioParams = {
            "command": config.command,
            "args": list(config.args),
        }
        if config.env:
            params["env"] = {**os.environ, **config.env}
        return MCPServerStdio(params=params, **common)
    headers = dict(config.headers)
    if config.transport == "sse":
        sse_params: MCPServerSseParams = {"url": config.url}
        if headers:
            sse_params["headers"] = headers
        return MCPServerSse(params=sse_params, **common)
    http_params: MCPServerStreamableHttpParams = {"url": config.url}
    if headers:
        http_params["headers"] = headers
    return MCPServerStreamableHttp(params=http_params, **common)


class McpClientManager:
    """持有本轮生效的 Server 连接；只启用 `enabled=True` 的配置。"""

    def __init__(
        self,
        configs: Sequence[McpServerConfig],
        *,
        connect_timeout_s: float = 10.0,
        session_timeout_s: float = 30.0,
    ) -> None:
        self._configs = [item for item in configs if item.enabled]
        self._servers: dict[str, Any] = {
            _server_key(item): build_server(item, session_timeout_s=session_timeout_s)
            for item in self._configs
        }
        self._manager = MCPServerManager(
            list(self._servers.values()),
            connect_timeout_seconds=connect_timeout_s,
            drop_failed_servers=True,
        )
        self._active: list[Any] = []

    async def connect(self) -> list[Any]:
        """并行连接；单个失败只记事件，不影响其他 Server 与本轮生成。"""
        if not self._servers:
            return []
        try:
            self._active = list(await self._manager.connect_all())
        except Exception:  # noqa: BLE001 - 连接层异常按「全部不可用」降级
            logger.warning("mcp.connect_all_failed", exc_info=True)
            self._active = []
        errors = self._manager.errors
        for key, server in self._servers.items():
            if server in self._active:
                emit("mcp.connected", server=key)
            else:
                error = errors.get(server)
                emit(
                    "mcp.connect_failed",
                    server=key,
                    error=type(error).__name__ if error is not None else "unknown",
                )
        return self._active

    async def cleanup(self) -> None:
        try:
            await self._manager.cleanup_all()
        except Exception:  # noqa: BLE001 - 清理失败不抛给业务
            logger.warning("mcp.cleanup_failed", exc_info=True)
        finally:
            self._active = []

    @property
    def servers(self) -> list[Any]:
        """已连接的 Server（接给 `Agent(mcp_servers=...)`）。"""
        return list(self._active)

    def statuses(self) -> list[dict[str, Any]]:
        errors = self._manager.errors
        out: list[dict[str, Any]] = []
        for key, server in self._servers.items():
            error = errors.get(server)
            out.append(
                {
                    "id": key,
                    "connected": server in self._active,
                    "error": type(error).__name__ if error is not None else "",
                }
            )
        return out


async def probe_server(config: McpServerConfig, *, timeout_s: float = 10.0) -> dict[str, Any]:
    """测试连接：连一次、列工具、立刻断开；失败返回错误类型而非抛异常。"""
    server = build_server(config, session_timeout_s=timeout_s)
    manager = MCPServerManager(
        [server], connect_timeout_seconds=timeout_s, drop_failed_servers=True
    )
    try:
        active = await manager.connect_all()
        if not active:
            error = manager.errors.get(server)
            return {
                "ok": False,
                "tools": [],
                "error": f"{type(error).__name__}: {error}" if error else "连接失败",
            }
        tools = await server.list_tools()
        return {
            "ok": True,
            "tools": [getattr(tool, "name", "") for tool in tools],
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - 测试连接只回报，不外抛
        return {"ok": False, "tools": [], "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            await manager.cleanup_all()
        except Exception:  # noqa: BLE001
            logger.debug("mcp.probe_cleanup_failed", exc_info=True)
