"""多波流水线（K6）：把工单列表拆成可安全串行执行的波次。

三步纯函数：依赖拓扑分层（Kahn，未知依赖容错、成环拒绝）→ 波内 scope_files
互斥贪心合并 → 结果按工单 id 落位。零 I/O；执行由调用方逐波经
`DelegationCoordinator` 走占位闸（本模块不派发）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from devprompt_ai.domain.agent.delegation import WorkerResult
from devprompt_ai.domain.agent.work_order import WorkOrder


@dataclass(frozen=True, slots=True)
class TeamWave:
    """一个可执行波次：波内工单互不占位冲突，且依赖已在前序波完成。"""

    index: int
    orders: tuple[WorkOrder, ...]


def plan_waves(orders: Sequence[WorkOrder]) -> tuple[TeamWave, ...]:
    """依赖拓扑分波 + 波内文件互斥。

    - `dependencies` 引用不存在的工单 id：视为无依赖（容错，不 fail 整批）；
    - 依赖成环或依赖不可满足：抛 ValueError（fail-closed，调用方降级为不派发）；
    - 同一波内 `scope_files` 必须互斥：冲突工单顺延到下一波。

    每轮迭代至少调度一个工单（ready 非空时首个必入波），循环必然终止。
    """
    by_id = {order.id: order for order in orders}
    if len(by_id) != len(orders):
        raise ValueError("工单 id 重复")
    remaining = dict(by_id)
    scheduled: set[str] = set()
    waves: list[TeamWave] = []
    while remaining:
        ready = [
            order
            for order in remaining.values()
            if all(dep in scheduled or dep not in by_id for dep in order.dependencies)
        ]
        if not ready:
            raise ValueError(f"工单依赖成环或依赖不可满足：{sorted(remaining)}")
        used: set[str] = set()
        wave: list[WorkOrder] = []
        for order in ready:
            files = set(order.scope_files)
            if files & used:
                continue
            wave.append(order)
            used |= files
        for order in wave:
            scheduled.add(order.id)
            del remaining[order.id]
        waves.append(TeamWave(index=len(waves), orders=tuple(wave)))
    return tuple(waves)


def merge_results(
    orders: Sequence[WorkOrder], results: Mapping[str, WorkerResult]
) -> dict[str, dict[str, Any]]:
    """结果按工单 id 落位；缺结果的工单按 blocked/未验证 记（K5 打捞纪律）。"""
    merged: dict[str, dict[str, Any]] = {}
    for order in orders:
        result = results.get(order.id)
        if result is None:
            merged[order.id] = {
                "status": "blocked",
                "summary": "",
                "salvaged": False,
                "evidence_status": "unverified",
            }
            continue
        merged[order.id] = {
            "status": result.status,
            "summary": result.output,
            "salvaged": result.salvaged,
            "evidence_status": result.evidence_status,
        }
    return merged
