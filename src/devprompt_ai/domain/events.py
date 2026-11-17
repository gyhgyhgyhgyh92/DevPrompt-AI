"""运行时事件（纯数据，零 I/O）。

事件是「对外可见变化」的唯一事实源：先落 ``run_events(seq)``，再扇出给订阅者。
``seq`` 按**会话**单调递增——多端订阅同一会话时凭它补差（`?since=N`）。

payload 必须已脱敏、已截断（MUST-19）；本模块不承担清洗职责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

#: 事件类型全集（与前端 `api/protocol.ts` 的类型守卫一一对应）。
EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "run.started",
        "thought",
        "action",
        "phase",
        "ask",
        "approval",
        "approval.resolved",
        "snapshot",
        "compact",
        "delegation",
        "stop",
        "error",
    }
)


@dataclass(frozen=True, slots=True)
class RunEvent:
    """一条会话事件。`seq` 从 1 开始，由存储层在事务内分配。"""

    session_id: str
    seq: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    created_at: str = ""

    def to_wire(self) -> dict[str, Any]:
        """SSE 帧体（字段名与前端约定的 snake_case 保持一致）。"""
        return {
            "seq": self.seq,
            "type": self.type,
            "run_id": self.run_id,
            "data": self.payload,
            "ts": self.created_at,
        }
