"""工单（K1）：委派的唯一原子。

写工必须声明 `scope_files`——没有范围就不知道隔离哪几个文件，也无法做冲突占位。
嵌套深度封顶 2：主会话是 0，子任务最多再分一层，防止「agent 生 agent」失控。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

MAX_DELEGATION_DEPTH: Final[int] = 2


@dataclass(frozen=True, slots=True)
class WorkOrder:
    id: str
    parent_turn_id: str
    profile: str
    objective: str
    scope_files: tuple[str, ...] = ()
    allowed_tools: frozenset[str] = frozenset()
    budget_ms: int = 60_000
    depth: int = 0
    dependencies: tuple[str, ...] = ()


def dedupe_key(order: WorkOrder) -> tuple[str, str, tuple[str, ...]]:
    return (order.profile, order.objective.strip(), order.scope_files)


def validate(order: WorkOrder, *, write: bool) -> None:
    """写工无范围、深度超限直接拒绝（fail-closed）。"""
    if write and not order.scope_files:
        raise ValueError("写工必须声明 scope_files")
    if order.depth > MAX_DELEGATION_DEPTH:
        raise ValueError(f"委派深度超限：{order.depth} > {MAX_DELEGATION_DEPTH}")
    if not order.objective.strip():
        raise ValueError("工单目标不能为空")


def child_depth(order: WorkOrder) -> int:
    return order.depth + 1
