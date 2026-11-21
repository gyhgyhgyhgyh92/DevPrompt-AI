"""MCP 工具审批：批准 / 拒绝 / 超时 / 无上下文，全部不得放行未授权调用。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from devprompt_ai.harness.mcp.approval import (
    ApprovalContext,
    approve_tool_call,
    reset_approval_context,
    set_approval_context,
)


class FakeBroker:
    def __init__(self, decision: str = "approve", *, resolved: bool = True) -> None:
        self.decision = decision
        self.resolved = resolved
        self.asked = 0

    async def ask(self, session_id: str, **kwargs: Any) -> SimpleNamespace:
        self.asked += 1
        return SimpleNamespace(request_id="req-1", session_id=session_id)

    async def wait(self, request_id: str, *, timeout_s: float = 60.0) -> Any:
        if not self.resolved:
            return None
        return SimpleNamespace(request_id=request_id, decision=self.decision)


def _tool(name: str = "write_file") -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_without_context_denies() -> None:
    assert _run(approve_tool_call(None, None, _tool())) is False


def test_approve_passes() -> None:
    token = set_approval_context(
        ApprovalContext(broker=FakeBroker("approve"), session_id="s1", run_id="r1")
    )
    try:
        assert _run(approve_tool_call(None, None, _tool())) is True
    finally:
        reset_approval_context(token)


def test_deny_and_timeout_block() -> None:
    for broker in (FakeBroker("deny"), FakeBroker(resolved=False)):
        token = set_approval_context(ApprovalContext(broker=broker, session_id="s1"))
        try:
            assert _run(approve_tool_call(None, None, _tool())) is False
            assert broker.asked == 1
        finally:
            reset_approval_context(token)
