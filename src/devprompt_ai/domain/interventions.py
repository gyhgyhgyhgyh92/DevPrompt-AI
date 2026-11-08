"""审批/提问的干预记录（纯数据）。

多端同时订阅时，**推送不去重**（谁都能看到弹框），去重压在应答层：
``resolve`` 用条件更新 `WHERE status='pending'`，只有第一个应答能把行置为 resolved。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

InterventionKind = Literal["approval", "question"]
InterventionStatus = Literal["pending", "resolved", "timeout", "cancelled"]

#: 允许的裁决值；缺字段一律按拒绝处理，**不做默认批准**。
VALID_DECISIONS: frozenset[str] = frozenset({"approve", "deny", "answer"})


@dataclass(frozen=True, slots=True)
class Intervention:
    request_id: str
    session_id: str
    run_id: str
    kind: InterventionKind
    payload: dict[str, Any] = field(default_factory=dict)
    status: InterventionStatus = "pending"
    decision: str = ""
    answer: str = ""
    created_at: str = ""
    resolved_at: str | None = None

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"
