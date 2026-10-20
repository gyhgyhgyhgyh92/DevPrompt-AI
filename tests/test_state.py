"""F-002 状态机测试：转移矩阵、乐观锁、恢复。"""

import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import FlowSession, SessionSummary
from devprompt_ai.state import FlowState, load_or_create, start_turn, transition


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

    async def list_recent(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        return [
            SessionSummary(
                session_id=s.session_id,
                state=s.state,
                project="",
                updated_at="",
            )
            for s in self.items.values()
            if s.user_id == user_id
        ][:limit]

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None


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


class TestStartTurn:
    """多轮（2026-10-20）：状态机作用域属于 turn，容器重开一轮不经 DONE 出边。"""

    async def test_reuses_finished_session_and_resets_to_init(self) -> None:
        store = FakeStore()
        session = FlowSession(session_id="s5", user_id="local", state=FlowState.DONE.value)
        store.items["s5"] = session

        started = await start_turn(store, "local", "s5")

        assert started.session_id == "s5"
        assert started.state == FlowState.INIT.value
        assert store.items["s5"].version == 1  # CAS 落盘

    async def test_refuses_while_previous_turn_running(self) -> None:
        store = FakeStore()
        session = FlowSession(session_id="s6", user_id="local", state=FlowState.ASKING.value)
        store.items["s6"] = session

        with pytest.raises(StateError) as caught:
            await start_turn(store, "local", "s6")

        assert caught.value.code == 6001
        assert session.state == FlowState.ASKING.value  # 不被误重置

    async def test_missing_session_raises_6003(self) -> None:
        with pytest.raises(StateError) as caught:
            await start_turn(FakeStore(), "local", "nope")
        assert caught.value.code == 6003

    async def test_other_user_session_raises_6003(self) -> None:
        store = FakeStore()
        store.items["s7"] = FlowSession(
            session_id="s7", user_id="someone-else", state=FlowState.DONE.value
        )
        with pytest.raises(StateError) as caught:
            await start_turn(store, "local", "s7")
        assert caught.value.code == 6003

    async def test_no_session_id_creates_new(self) -> None:
        store = FakeStore()
        session = await start_turn(store, "local", None)
        assert session.state == FlowState.INIT.value
        assert store.items[session.session_id] is session
