"""MCP 连接的进程级复用（2026-11-21）：按配置指纹缓存，配置变了才重连。

为什么不做成「每次生成新建连接」：stdio Server 要起子进程，每轮重启既慢又
可能丢状态；做成「每次调用建连」还会让多个并发会话互相抢同一份配置。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence

from pydantic import ValidationError

from devprompt_ai.domain.mcp.models import McpServerConfig
from devprompt_ai.harness.mcp.manager import McpClientManager

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_manager: McpClientManager | None = None
_fingerprint = ""


def parse_servers(raw: Sequence[dict[str, object]]) -> list[McpServerConfig]:
    """坏配置逐条跳过：一条写错不该让整轮生成连不上任何 MCP。"""
    out: list[McpServerConfig] = []
    for item in raw:
        try:
            # model_validate 而非 ** 解包：解包时 mypy 无法校验键与类型，
            # 而 pydantic 的运行时校验同样覆盖（坏配置照旧被 ValidationError 捕获）。
            out.append(McpServerConfig.model_validate(dict(item)))
        except ValidationError:
            logger.info("mcp.config_invalid", extra={"name": str(item.get("name", ""))})
    return out


async def get_servers(
    configs: Sequence[McpServerConfig],
    *,
    enabled: bool = True,
    connect_timeout_s: float = 10.0,
) -> list[object]:
    """返回已连接的 Server；关闭或无配置时返回空列表（调用方零分支）。"""
    global _manager, _fingerprint
    enabled_configs = [item for item in configs if item.enabled]
    if not enabled or not enabled_configs:
        return []
    fingerprint = json.dumps([item.model_dump() for item in enabled_configs], sort_keys=True)
    async with _lock:
        if _manager is not None and fingerprint == _fingerprint:
            return _manager.servers
        if _manager is not None:
            await _manager.cleanup()
        manager = McpClientManager(enabled_configs, connect_timeout_s=connect_timeout_s)
        await manager.connect()
        _manager = manager
        _fingerprint = fingerprint
        return manager.servers


async def close() -> None:
    global _manager, _fingerprint
    async with _lock:
        if _manager is not None:
            await _manager.cleanup()
        _manager = None
        _fingerprint = ""
