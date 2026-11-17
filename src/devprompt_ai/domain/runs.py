"""运行记录（纯数据）：一次执行的生命周期。

与 ``FlowState`` 的关系：状态机描述**流程到哪一步**，运行记录描述**这次执行的结果**。
两者不是一回事——一个 turn 可能因用户中止而 ABORTED，也可能因服务器重启而无终态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RunStatus = Literal["queued", "running", "done", "error", "aborted"]

#: 终态集合：进入后不再推进，``ended_at`` 必须落值。
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"done", "error", "aborted"})


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    session_id: str
    turn_index: int
    status: RunStatus
    stop_reason: str = ""
    request_id: str = ""
    model_id: str = ""
    error_code: int | None = None
    error_message: str = ""
    started_at: str = ""
    ended_at: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES
