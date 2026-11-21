"""MCP 工具调用审批：复用现有干预通道，超时按拒绝处理。

为什么用 ContextVar 而非构造参数：MCP Server 连接是**跨会话复用**的，
而审批人（哪个会话、哪个 run）是每轮才确定。若把会话绑进 Server 构造函数，
就得多会话各起一份进程——代价远高于一次上下文切换。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from devprompt_ai.observability.logging import emit

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovalContext:
    """当前轮次的审批落点：broker + 会话 + run + 超时。"""

    broker: Any
    session_id: str
    run_id: str = ""
    timeout_s: float = 60.0


_APPROVAL: ContextVar[ApprovalContext | None] = ContextVar("devprompt_mcp_approval", default=None)


def set_approval_context(context: ApprovalContext | None) -> Token[ApprovalContext | None]:
    return _APPROVAL.set(context)


def reset_approval_context(token: Token[ApprovalContext | None]) -> None:
    _APPROVAL.reset(token)


async def approve_tool_call(_context: Any, _agent: Any, tool: Any) -> bool:
    """SDK 的 require_approval 回调：无上下文（后台/测试）一律拒绝。"""
    ctx = _APPROVAL.get()
    name = str(getattr(tool, "name", "") or "")
    if ctx is None:
        emit("mcp.approval_denied", tool=name, reason="no_context")
        return False
    try:
        item = await ctx.broker.ask(
            ctx.session_id,
            run_id=ctx.run_id,
            kind="approval",
            payload={"tool": name, "reason": "MCP 工具将执行外部操作"},
        )
    except Exception:  # noqa: BLE001 - 审批通道故障按拒绝处理，不放行
        logger.warning("mcp.approval_ask_failed", exc_info=True)
        return False
    emit("mcp.approval_requested", tool=name, request_id=item.request_id)
    resolved = await ctx.broker.wait(item.request_id, timeout_s=ctx.timeout_s)
    if resolved is None:
        emit("mcp.approval_timeout", tool=name, request_id=item.request_id)
        return False
    if resolved.decision != "approve":
        emit("mcp.approval_denied", tool=name, request_id=item.request_id)
        return False
    return True
