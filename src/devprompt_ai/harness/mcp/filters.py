"""MCP 工具白名单 → SDK 的静态过滤对象。

空白名单表示「不限制」——这是 ui 更常用的语义（用户不填就全开）；
写成空数组却当成「全禁」会让人以为连接坏了。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agents.mcp import create_static_tool_filter


def build_tool_filter(allowlist: Sequence[str]) -> Any:
    names = [item.strip() for item in allowlist if item.strip()]
    if not names:
        return None
    return create_static_tool_filter(allowed_tool_names=names)
