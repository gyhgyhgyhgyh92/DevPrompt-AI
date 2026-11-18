"""批处理规划（C11）：先判定并发性再派发，结果按原 index 落位。

规则：连续的只读项并成一批；写项各自成批并作为屏障——写之后的操作必须看到
写入结果，因此不能与写并发。

状态（2026-11-18 接线）：`service._run_delegation_waves` 在委派波内用本模块分批
（只读批并发、写批串行），并发容量由 `DelegationCoordinator` 的分池信号量约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BatchItem:
    index: int
    name: str
    read_only: bool


def plan_batches(items: list[BatchItem]) -> list[list[BatchItem]]:
    batches: list[list[BatchItem]] = []
    current: list[BatchItem] = []
    for item in items:
        if item.read_only:
            current.append(item)
            continue
        if current:
            batches.append(current)
            current = []
        batches.append([item])
    if current:
        batches.append(current)
    return batches


def merge_results(batches: list[list[BatchItem]], results: list[T]) -> list[T]:
    """results 与 batches 展平后的顺序一致；按原始 index 复原。"""
    ordered: list[tuple[int, T]] = []
    cursor = 0
    for batch in batches:
        for item in batch:
            ordered.append((item.index, results[cursor]))
            cursor += 1
    ordered.sort(key=lambda pair: pair[0])
    return [value for _, value in ordered]
