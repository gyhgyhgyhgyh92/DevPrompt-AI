"""撤销（物理删除）测试：删后轮、保留前轮、终态校验、归属校验、事件留痕。

后续轮次用 ``turns.append`` 直接落库构造（真实跑会停在 ASKING，与被测逻辑无关）；
被测对象是 ``rollback_to_turn`` 的删除范围、数据重建与校验，不覆盖生成链路。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import pytest

from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.models import TurnRecord
from devprompt_ai.memory.turn_store import SQLiteTurnStore
from test_service import _service


async def _make_three_turns(tmp_path: Any) -> tuple[Any, Any, list[str]]:
    """第 1 轮走真实流程（DONE），第 2/3 轮直接落库，返回各轮 turn_id。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, store = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)
    first = await svc.optimize("local", ".", "第一轮：把提交按钮改成 primary-500", request_id="r1")
    assert first.status == "done"

    session_id = first.session_id
    records = await turns.list_for_session(session_id)
    base = records[0]
    for index in (1, 2):
        await turns.append(
            replace(base, turn_index=index, turn_id=f"turn-{index}", input=f"第{index + 1}轮原句")
        )
    return svc, store, [base.turn_id, "turn-1", "turn-2"]


async def test_rollback_deletes_later_turns_and_rebuilds_data(tmp_path: Any) -> None:
    """撤销到第 1 轮：第 2/3 轮物理消失，会话数据回到第 1 轮完成时。"""
    svc, store, turn_ids = await _make_three_turns(tmp_path)
    session_id = next(iter(store.items))
    first_turn_id = turn_ids[0]

    snap = await svc.rollback_to_turn("local", session_id, first_turn_id)

    assert snap.status == "done"
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    remaining = await turns.list_for_session(session_id)
    assert [r.turn_index for r in remaining] == [0]
    session = store.items[session_id]
    assert session.data["turn_index"] == 0
    assert session.data["sentence"] == "第一轮：把提交按钮改成 primary-500"
    assert session.data["variant"], "第 1 轮的方案应作为本轮 data 起点"
    assert session.data["turn_memory"]["facts"], "第 1 轮取证应进 turn_memory"


async def test_rollback_records_event(tmp_path: Any, caplog: Any) -> None:
    """留痕：session.rolled_back 带 kept/deleted 计数（不记原句，MUST-19）。"""
    svc, store, turn_ids = await _make_three_turns(tmp_path)
    session_id = next(iter(store.items))

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        await svc.rollback_to_turn("local", session_id, turn_ids[0])

    rolled = [r for r in caplog.records if r.getMessage() == "session.rolled_back"]
    assert len(rolled) == 1
    assert getattr(rolled[0], "deleted_turns", None) == 2
    assert getattr(rolled[0], "kept_turns", None) == 1


async def test_rollback_rejected_while_session_active(tmp_path: Any) -> None:
    """非终态（反问中等用户）不允许撤销——进行中的轮次正在被写。"""
    svc, store, turn_ids = await _make_three_turns(tmp_path)
    session_id = next(iter(store.items))
    from devprompt_ai.state import FlowState

    store.items[session_id].state = FlowState.ASKING.value
    with pytest.raises(DevPromptError) as exc:
        await svc.rollback_to_turn("local", session_id, turn_ids[1])
    assert exc.value.code == 6001


async def test_rollback_rejects_foreign_turn(tmp_path: Any) -> None:
    """轮次不属于该会话：拒绝（防跨会话误删）。"""
    svc, store, _ = await _make_three_turns(tmp_path)
    session_id = next(iter(store.items))
    other = await svc.optimize("local", ".", "另一会话的第一轮", request_id="r9")
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    others = await turns.list_for_session(other.session_id)

    with pytest.raises(DevPromptError) as exc:
        await svc.rollback_to_turn("local", session_id, others[0].turn_id)
    assert exc.value.code == 1001


async def test_delete_after_keeps_baseline_and_before(tmp_path: Any) -> None:
    """存储层直测：delete_after 只删 turn_index 之后的行，返回删除数。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)
    first = await svc.optimize("local", ".", "第一轮", request_id="r1")
    records = await turns.list_for_session(first.session_id)
    base: TurnRecord = records[0]
    for index in (1, 2, 3):
        await turns.append(replace(base, turn_index=index, turn_id=f"t{index}"))

    deleted = await turns.delete_after(first.session_id, 1)

    assert deleted == 2
    remaining = await turns.list_for_session(first.session_id)
    assert [r.turn_index for r in remaining] == [0, 1]
