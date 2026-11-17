"""子 agent 与权限测试：工单、去重、冲突、打捞、调度槽位与审批。"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.agent.delegation import (
    can_run,
    conflicts,
    parse_worker_output,
    plan_orders,
)
from devprompt_ai.domain.agent.profile_registry import allowed_tools, get_profile
from devprompt_ai.domain.agent.work_order import WorkOrder, dedupe_key, validate
from devprompt_ai.domain.permissions import (
    ApprovalMode,
    PermissionPolicy,
    PermissionRequest,
    Risk,
)
from devprompt_ai.harness.worktree import branch_name, create_args, worktree_path
from devprompt_ai.runtime.coordinator import DelegationCoordinator


def _order(
    oid: str = "o1",
    *,
    profile: str = "code_scout",
    files: tuple[str, ...] = ("a.py",),
    depth: int = 0,
    deps: tuple[str, ...] = (),
) -> WorkOrder:
    return WorkOrder(
        id=oid,
        parent_turn_id="t1",
        profile=profile,
        objective="查清现状",
        scope_files=files,
        depth=depth,
        dependencies=deps,
    )


def test_work_order_validation() -> None:
    with pytest.raises(ValueError):
        validate(_order(files=()), write=True)
    with pytest.raises(ValueError):
        validate(_order(depth=3), write=False)
    with pytest.raises(ValueError):
        validate(WorkOrder("x", "t", "code_scout", " "), write=False)
    validate(_order(), write=False)


def test_dedupe_and_conflicts() -> None:
    first = _order("a")
    duplicate = _order("b")

    assert dedupe_key(first) == dedupe_key(duplicate)
    assert [order.id for order in plan_orders([first, duplicate])] == ["a"]

    assert conflicts({"a.py"}, {"a.py", "b.py"}) == {"a.py"}
    assert can_run(_order(), {"b.py"}) is True
    assert can_run(_order(), {"a.py"}) is False
    assert can_run(_order(deps=("x",)), set()) is False


def test_worker_output_salvage_is_marked_unverified() -> None:
    ok = parse_worker_output('{"summary": "查清了导出", "evidence": ["a.py:1"]}')
    malformed = parse_worker_output("这不是 JSON")
    missing = parse_worker_output('{"summary": "随便"}', required_terms=["导出"])
    empty = parse_worker_output("   ")

    assert ok.status == "ok" and ok.evidence_status == "verified"
    assert malformed.status == "partial" and malformed.salvaged is True
    assert malformed.evidence_status == "unverified"
    assert missing.status == "partial" and missing.salvaged is True
    assert empty.status == "blocked"


def test_profiles_are_fail_closed() -> None:
    assert get_profile("unknown") is None
    assert allowed_tools("unknown") == frozenset()
    assert get_profile("patcher") is not None
    assert get_profile("patcher").write is True  # type: ignore[union-attr]
    assert "write_file" not in allowed_tools("code_scout")


def test_permissions_deny_before_everything() -> None:
    policy = PermissionPolicy(mode=ApprovalMode.BYPASS)
    decision = policy.authorize(PermissionRequest("bash", command="sudo rm -rf /"))

    assert decision.allowed is False
    assert decision.reason == "denied-pattern"


def test_permissions_unconditional_tool_still_asks() -> None:
    policy = PermissionPolicy(mode=ApprovalMode.AUTO_SAFE)
    decision = policy.authorize(PermissionRequest("js_eval", risk=Risk.NONE))

    assert decision.allowed is False
    assert decision.needs_approval is True


def test_permissions_four_layer_memory() -> None:
    policy = PermissionPolicy(mode=ApprovalMode.MANUAL)
    assert policy.authorize(PermissionRequest("bash", command="rg foo")).needs_approval is True

    policy.remember_bash("rg ")
    assert policy.authorize(PermissionRequest("bash", command="rg foo")).allowed is True

    policy.remember_file("src/a.py")
    assert policy.authorize(PermissionRequest("write_file", path="src/a.py")).allowed is True

    policy.grant_path("src/ui/")
    assert policy.authorize(PermissionRequest("write_file", path="src/ui/b.tsx")).allowed is True

    policy.allowlist.add("read_file")
    assert policy.authorize(PermissionRequest("read_file")).allowed is True


def test_permissions_auto_safe_and_recheck() -> None:
    policy = PermissionPolicy(mode=ApprovalMode.AUTO_SAFE)

    assert policy.authorize(PermissionRequest("grep", risk=Risk.LOW)).allowed is True
    assert policy.authorize(PermissionRequest("write_file", risk=Risk.HIGH)).needs_approval is True

    edited = PermissionRequest("bash", command="sudo cat /etc/passwd")
    assert policy.recheck_after_edit(edited).allowed is False, "改过的输入必须重跑 deny 门"


async def test_coordinator_registers_and_releases_files() -> None:
    coordinator = DelegationCoordinator(total_cap=2, explore_cap=1, write_cap=1)

    async def worker(order: WorkOrder) -> str:
        assert "a.py" in coordinator.inflight
        return order.id

    assert await coordinator.run(_order(), worker) == "o1"
    assert coordinator.inflight == frozenset(), "结束后必须释放占位"

    assert coordinator.can_run(_order(profile="unknown")) is False


async def test_coordinator_rejects_conflicting_order() -> None:
    coordinator = DelegationCoordinator()
    coordinator._inflight.add("a.py")  # type: ignore[attr-defined]

    with pytest.raises(ValueError):
        await coordinator.run(_order(), lambda order: None)  # type: ignore[arg-type]


def test_worktree_args_are_pure() -> None:
    assert branch_name("abcdef123456") == "devprompt-hands-abcdef12"
    assert worktree_path("D:/repo", "abcdef123456").endswith(".devprompt-worktrees/abcdef12")

    args = create_args("D:/repo", "abcdef123456")
    assert args[:3] == ["git", "-C", "D:/repo"]
    assert "worktree" in args and "add" in args
