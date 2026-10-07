"""F-002 状态机测试：转移矩阵、乐观锁、恢复。"""

import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.state import FlowState, load_or_create, transition


class FakeStore:
    def __init__(self, fail_save: bool = False) -> None:
        self.items: dict[str, FlowSession] = {}
        self.fail_save = fail_save

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        if self.fail_save:
            return False
        self.items[session.session_id] = session
        session.version += 1
        return True


def test_all_states_have_transitions() -> None:
    from devprompt_ai.state import TRANSITIONS

    assert set(TRANSITIONS) == set(FlowState)
    assert len(list(FlowState)) == 9


async def test_legal_transition_persists() -> None:
    store = FakeStore()
    session = FlowSession(session_id="s1", user_id="local", state=FlowState.INIT.value)
    store.items["s1"] = session
    await transition(session, FlowState.RETRIEVING, store)
    assert session.state == "RETRIEVING"
    assert store.items["s1"].version == 1


async def test_illegal_transition_raises_6001() -> None:
    store = FakeStore()
    session = FlowSession(session_id="s2", user_id="local", state=FlowState.INIT.value)
    store.items["s2"] = session
    with pytest.raises(StateError) as ei:
        await transition(session, FlowState.DONE, store)
    assert ei.value.code == 6001
    assert session.state == FlowState.INIT.value  # 非法转移不落盘


async def test_cas_conflict_raises_6001() -> None:
    store = FakeStore(fail_save=True)
    session = FlowSession(session_id="s3", user_id="local", state=FlowState.PROBING.value)
    store.items["s3"] = session
    with pytest.raises(StateError) as ei:
        await transition(session, FlowState.ASKING, store)
    assert ei.value.code == 6001


async def test_load_or_create_existing_and_missing() -> None:
    store = FakeStore()
    session = FlowSession(session_id="s4", user_id="local", state=FlowState.INIT.value)
    store.items["s4"] = session
    got = await load_or_create(store, "local", "s4")
    assert got.session_id == "s4"
    with pytest.raises(StateError) as ei:
        await load_or_create(store, "local", "missing")
    assert ei.value.code == 6003


async def test_load_or_create_new() -> None:
    store = FakeStore()
    session = await load_or_create(store, "local")
    assert session.state == FlowState.INIT.value
    assert store.items[session.session_id] is session
