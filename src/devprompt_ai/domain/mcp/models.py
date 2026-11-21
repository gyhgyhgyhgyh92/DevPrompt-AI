"""MCP Server 配置模型与校验（纯数据，零 I/O）。

stdio 等于「执行任意本地命令」，因此校验放在领域层：**任何入口（HTTP、设置文件、
测试）都必须过同一套规则**，不依赖前端自觉。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Transport = Literal["stdio", "sse", "streamable-http"]

#: shell 元字符：stdio 走子进程数组传参（不经 shell），但仍拒绝这些字符，
#: 避免用户在命令里塞「&& rm -rf」这类跨命令拼接造成误执行。
_SHELL_META = re.compile(r"[;&|><`$]")
#: 敏感键：回显时掩码（与 provider_configs 同一口径）。
_SENSITIVE_HINTS = ("key", "token", "secret", "password", "authorization")


def is_sensitive_key(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def mask_mapping(values: dict[str, str]) -> dict[str, str]:
    """敏感键回显为掩码；空值保持为空（前端据此沿用旧值）。"""
    return {
        key: ("••••••" if is_sensitive_key(key) and value else value)
        for key, value in values.items()
    }


class McpServerConfig(BaseModel):
    """一个外部 MCP Server 的连接配置。"""

    id: str = ""
    name: str
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    #: 空列表 = 允许该 Server 的全部工具。
    tool_allowlist: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> McpServerConfig:
        name = self.name.strip()
        if not name:
            raise ValueError("MCP Server 名称不能为空")
        if self.transport == "stdio":
            command = self.command.strip()
            if not command:
                raise ValueError(f"{name}：stdio 模式必须填写命令")
            if _SHELL_META.search(command) or any(_SHELL_META.search(a) for a in self.args):
                raise ValueError(f"{name}：命令与参数不得包含 shell 元字符（; & | > < ` $）")
        else:
            if not self.url.strip().lower().startswith(("http://", "https://")):
                raise ValueError(f"{name}：{self.transport} 模式的地址必须以 http(s):// 开头")
        return self

    def public_view(self) -> dict[str, object]:
        """脱敏视图：env/headers 的敏感键只回掩码；命令与地址原样（便于排障）。"""
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "env": mask_mapping(self.env),
            "url": self.url,
            "headers": mask_mapping(self.headers),
            "enabled": self.enabled,
            "tool_allowlist": list(self.tool_allowlist),
        }
