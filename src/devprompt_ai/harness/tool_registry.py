"""工具注册表（C6–C9）：同名覆盖可观测、晚到注册可等待、别名先归一、档位可裁剪。

「晚到注册」指 MCP/插件异步注册：首个请求发出前若工具数组还在变，会击碎已缓存的
prompt 前缀；这里用 8s 封顶的闸门把抖动吸收到用户边界。

状态（2026-11-18 接线）：`service._execute_action_inner` 以本注册表为动作分发唯一入口
（8 个 Agent 动作 → handler，未注册动作告警降级）。`LateRegistrationGate` 保留为 MCP/插件
动态注册预留——当前无注册来源，故无消费方，仅单测覆盖；接入插件注册时直接启用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Hashable
from typing import Final, Generic, TypeVar

T = TypeVar("T", bound=Hashable)

#: 外来名 → 本项目动作名；必须在权限/策略判定**之前**归一，避免别名绕过规则。
ALIASES: Final[dict[str, str]] = {
    "task": "delegate_task",
    "agent": "delegate_task",
    "todowrite": "todo",
    "read": "read_file",
    "write": "write_file",
}

#: 档位：None 表示不裁剪。
PRESETS: Final[dict[str, frozenset[str] | None]] = {
    "minimal": frozenset({"read_file", "grep", "glob", "bash", "retrieve", "probe"}),
    "full": None,
}

DEFAULT_REGISTRATION_TIMEOUT_S: Final[float] = 8.0


def normalize_name(name: str) -> str:
    return ALIASES.get(name, name)


class ToolRegistry(Generic[T]):
    def __init__(self) -> None:
        self._tools: dict[str, T] = {}
        self._overwritten: set[str] = set()

    def register(self, name: str, tool: T) -> bool:
        """返回 True 表示发生了覆盖（调用方据此告警，但不改变覆盖行为）。"""
        canonical = normalize_name(name)
        overwritten = canonical in self._tools
        self._tools[canonical] = tool
        if overwritten:
            self._overwritten.add(canonical)
        return overwritten

    def get(self, name: str) -> T | None:
        return self._tools.get(normalize_name(name))

    def names(self, preset: str = "full") -> list[str]:
        allowed = PRESETS.get(preset, PRESETS["full"])
        if allowed is None:
            return sorted(self._tools)
        return sorted(name for name in self._tools if name in allowed)

    def overwritten(self) -> frozenset[str]:
        return frozenset(self._overwritten)


class LateRegistrationGate:
    """首请求前等待异步注册；超时放行（不挂死会话）。"""

    def __init__(self, *, timeout_s: float = DEFAULT_REGISTRATION_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._pending = 0
        self._ready = asyncio.Event()
        self._ready.set()

    def begin(self) -> None:
        self._pending += 1
        self._ready.clear()

    def end(self) -> None:
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._ready.set()

    @property
    def pending(self) -> int:
        return self._pending

    async def wait(self, on_timeout: Callable[[], None] | None = None) -> bool:
        """等待注册完成；返回 False 表示超时（调用方记录但不阻断）。"""
        if self._pending == 0:
            return True
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self._timeout_s)
        except TimeoutError:
            if on_timeout is not None:
                on_timeout()
            return False
        return True
