"""并行验证暴露问题的回归：终态语义、快照序列化契约、初始化串行约束。"""

from __future__ import annotations

import json

from devprompt_ai.domain.agent.stop_reason import StopReason, snapshot_stop_reason
from devprompt_ai.interfaces.api.routes import _snapshot_payload
from devprompt_ai.service import FlowSnapshot


def test_ask_terminal_is_await_user_not_finished() -> None:
    reason = snapshot_stop_reason("ask", "ASKING")
    assert reason is StopReason.AWAIT_USER
    assert reason.value == "await-user"
    assert reason not in {StopReason.NATURAL_FINISH, StopReason.END_TURN}


def test_official_snapshot_serializer_is_json_safe() -> None:
    """序列化器须产出可直接落 SSE/SQLite 的 JSON（裸 asdict 会在嵌套 pydantic 上炸）。"""
    snapshot = FlowSnapshot(session_id="s1", status="done", state="DONE")
    payload = _snapshot_payload(snapshot).model_dump(mode="json")

    assert "status" in payload and "state" in payload
    assert json.loads(json.dumps(payload, ensure_ascii=False))["status"] == "done"
