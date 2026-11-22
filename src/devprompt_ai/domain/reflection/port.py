"""Reflection（自进化）接口：外部经验库的读写契约（2026-11-22）。

只声明「我需要什么能力」，不关心经验从哪来、存哪里——实现由基础设施层提供、
在 service 组装时注入（MUST-06：domain 只依赖 Protocol，零 I/O）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class ReflectionScope(str, Enum):
    """经验桶：PROJECT 跟随 project_root，GLOBAL 跨项目复用。"""

    PROJECT = "project"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class ReflectionHit:
    """一条召回的候选经验（text 已是可直接注入的纯文本）。"""

    scope: ReflectionScope
    text: str
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class ReflectionNote:
    """一轮结束写回的经验。

    全局桶跨项目共享，``target`` / ``paths`` 必须为空——由调用方负责不填。
    """

    scope: ReflectionScope
    summary: str
    #: 仅 PROJECT 桶需要：实现侧据此算出项目桶 id（全局桶留空）。
    project_root: str = ""
    domain: str = ""
    stop_reason: str = ""
    target: str = ""
    paths: tuple[str, ...] = ()


@runtime_checkable
class ReflectionPort(Protocol):
    """经验库端口：生成前召回、turn 收尾写入。"""

    async def recall(
        self, *, sentence: str, domain: str, project_root: str
    ) -> tuple[ReflectionHit, ...]:
        """返回按相关度排序的候选；不可用时返回空元组，不向调用方抛异常。"""
        ...

    async def record(self, note: ReflectionNote) -> bool:
        """写入一条经验；失败静默（旁路增强，不阻断主流程）。

        返回 ``True`` 表示确实提交给了经验库，``False`` 表示被跳过或失败——
        调用方据此决定是否上报「已记录」，避免把未落盘也报成成功（MUST-11d）。
        """
        ...
