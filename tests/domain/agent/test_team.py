"""K6 多波流水线测试：拓扑分波、文件互斥、成环拒绝与结果落位。"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.agent.delegation import WorkerResult
from devprompt_ai.domain.agent.team import merge_results, plan_waves
from devprompt_ai.domain.agent.work_order import WorkOrder


def _order(id: str, *, deps: tuple[str, ...] = (), files: tuple[str, ...] = ()) -> WorkOrder:
    return WorkOrder(
        id=id,
        parent_turn_id="t",
        profile="code_scout",
        objective=f"任务 {id}",
        scope_files=files,
        dependencies=deps,
    )


def test_independent_orders_share_one_wave() -> None:
    orders = [_order("a", files=("a.py",)), _order("b", files=("b.py",))]

    waves = plan_waves(orders)

    assert len(waves) == 1
    assert [o.id for o in waves[0].orders] == ["a", "b"]


def test_overlapping_files_split_into_waves() -> None:
    orders = [_order("a", files=("shared.py",)), _order("b", files=("shared.py",))]

    waves = plan_waves(orders)

    assert len(waves) == 2, "同文件互斥：第二个工单顺延下一波"
    assert [o.id for o in waves[0].orders] == ["a"]
    assert [o.id for o in waves[1].orders] == ["b"]


def test_dependencies_run_before_dependents() -> None:
    orders = [
        _order("b", deps=("a",)),
        _order("a", files=("a.py",)),
        _order("c", deps=("b",), files=("c.py",)),
    ]

    waves = plan_waves(orders)

    order_of = {o.id: wave.index for wave in waves for o in wave.orders}
    assert order_of["a"] < order_of["b"] < order_of["c"]


def test_unknown_dependency_is_tolerated() -> None:
    orders = [_order("a", deps=("ghost",))]

    waves = plan_waves(orders)

    assert len(waves) == 1 and [o.id for o in waves[0].orders] == ["a"]


def test_cycle_is_rejected() -> None:
    orders = [_order("a", deps=("b",)), _order("b", deps=("a",))]

    with pytest.raises(ValueError, match="成环"):
        plan_waves(orders)


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="重复"):
        plan_waves([_order("a"), _order("a")])


def test_merge_results_falls_back_to_blocked() -> None:
    orders = [_order("a"), _order("b")]
    results = {
        "a": WorkerResult("ok", output="结论", evidence=("a.py:1",), evidence_status="verified")
    }

    merged = merge_results(orders, results)

    assert merged["a"]["status"] == "ok"
    assert merged["b"] == {
        "status": "blocked",
        "summary": "",
        "salvaged": False,
        "evidence_status": "unverified",
    }, "缺结果按 blocked/未验证 记（K5 打捞纪律）"
