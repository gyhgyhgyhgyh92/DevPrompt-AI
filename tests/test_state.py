"""F-002 状态机测试：星型转移矩阵、经 AGENTIC 中转、乐观锁、恢复。

星型拓扑（2026-11-04）：AGENTIC 是唯一枢纽，执行态完成后一律回到它。
此处逐条锁死拓扑不变量，防止后续改动悄悄加回执行态之间的直连边。
"""

import pytest

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import FlowSession, SessionSummary
from devprompt_ai.state import (
    ACTIVE_STATES,
    TRANSITIONS,
    FlowState,
    hop,
    load_or_create,
    start_turn,
    transition,
)

#: 唯一被允许的「不经 AGENTIC 的执行态直连」，均为既有快速路径。
FAST_PATH: dict[FlowState, frozenset[FlowState]] = {
    FlowState.GENERATING: frozenset({FlowState.DONE}),
}


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

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
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

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        return 0  # 本用例不覆盖项目级删除（详见 test_session_store.py）


# ── 拓扑不变量 ──────────────────────────────────────────────────────


def test_all_states_have_transitions() -> None:
    assert set(TRANSITIONS) == set(FlowState)
    assert len(list(FlowState)) == 9
    assert not hasattr(FlowState, "RANKING")


def test_init_only_leads_to_agentic_or_aborted() -> None:
    assert TRANSITIONS[FlowState.INIT] == frozenset({FlowState.AGENTIC, FlowState.ABORTED})


def test_every_execution_state_returns_to_agentic() -> None:
    """除终态与枢纽自身外，每个态都必须能回到 AGENTIC。"""
    for state in FlowState:
        if state in (FlowState.DONE, FlowState.ABORTED, FlowState.AGENTIC):
            continue
        assert FlowState.AGENTIC in TRANSITIONS[state], state


def test_no_execution_state_skips_agentic() -> None:
    """执行态之间不得直连，唯一例外是 FAST_PATH 里登记的既有快速路径。"""
    for state in FlowState:
        if state in (FlowState.DONE, FlowState.ABORTED, FlowState.AGENTIC):
            continue
        extra = TRANSITIONS[state] - {FlowState.AGENTIC, FlowState.ABORTED}
        assert extra <= FAST_PATH.get(state, frozenset()), state


def test_agentic_reaches_every_execution_state() -> None:
    assert {
        FlowState.RETRIEVING,
        FlowState.PROBING,
        FlowState.ASKING,
        FlowState.CONFIRMING,
        FlowState.GENERATING,
        FlowState.DONE,
        FlowState.ABORTED,
    } <= TRANSITIONS[FlowState.AGENTIC]


def test_terminal_states_have_no_outgoing_edges() -> None:
    assert TRANSITIONS[FlowState.DONE] == frozenset()
    assert TRANSITIONS[FlowState.ABORTED] == frozenset()


def test_active_states_exclude_waiting_and_terminal() -> None:
    """活跃态用于启动期孤儿扫描：等用户与终态都不算崩溃孤儿。"""
    assert FlowState.AGENTIC in ACTIVE_STATES
    assert FlowState.INIT in ACTIVE_STATES
    assert FlowState.RETRIEVING in ACTIVE_STATES
    assert FlowState.GENERATING in ACTIVE_STATES
    assert FlowState.ASKING not in ACTIVE_STATES
    assert FlowState.CONFIRMING not in ACTIVE_STATES
    assert FlowState.DONE not in ACTIVE_STATES
    assert FlowState.ABORTED not in ACTIVE_STATES


# ── 基础转移 ────────────────────────────────────────────────────────


async def test_legal_transition_persists() -> None:
    store = FakeStore()
    session = FlowSession(session_id="s1", user_id="local", state=FlowState.INIT.value)
    store.items["s1"] = session
    await transition(session, FlowState.AGENTIC, store)
    assert session.state == "AGENTIC"
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
        await transition(session, FlowState.AGENTIC, store)
    assert ei.value.code == 6001


# ── 经 AGENTIC 中转 ─────────────────────────────────────────────────


async def test_hop_inserts_agentic() -> None:
    store = FakeStore()
    session = FlowSession(session_id="h1", user_id="local", state=FlowState.INIT.value)
    store.items["h1"] = session

    await hop(session, FlowState.RETRIEVING, store)

    assert session.state == "RETRIEVING"
    assert store.items["h1"].version == 2  # INIT→AGENTIC→RETRIEVING 两次 CAS


async def test_hop_from_agentic_does_not_self_loop() -> None:
    store = FakeStore()
    session = FlowSession(session_id="h2", user_id="local", state=FlowState.AGENTIC.value)
    store.items["h2"] = session

    await hop(session, FlowState.PROBING, store)

    assert session.state == "PROBING"
    assert store.items["h2"].version == 1


async def test_hop_to_agentic_only_returns_home() -> None:
    store = FakeStore()
    session = FlowSession(session_id="h3", user_id="local", state=FlowState.GENERATING.value)
    store.items["h3"] = session

    await hop(session, FlowState.AGENTIC, store)

    assert session.state == "AGENTIC"
    assert store.items["h3"].version == 1


async def test_hop_from_terminal_raises_6001() -> None:
    """DONE 无出边：必须先 start_turn 重置容器，不能经 hop 偷渡。"""
    store = FakeStore()
    session = FlowSession(session_id="h4", user_id="local", state=FlowState.DONE.value)
    store.items["h4"] = session

    with pytest.raises(StateError) as ei:
        await hop(session, FlowState.RETRIEVING, store)

    assert ei.value.code == 6001
    assert session.state == FlowState.DONE.value


# ── 会话装载 ────────────────────────────────────────────────────────


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
    """多轮：状态机作用域属于 turn，容器重开一轮不经 DONE 出边。"""

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

    async def test_refuses_while_agentic_running(self) -> None:
        """AGENTIC 属活跃态：崩溃遗留的 AGENTIC 由启动自愈置为 ABORTED 后才可重开。"""
        store = FakeStore()
        session = FlowSession(session_id="s8", user_id="local", state=FlowState.AGENTIC.value)
        store.items["s8"] = session

        with pytest.raises(StateError) as caught:
            await start_turn(store, "local", "s8")

        assert caught.value.code == 6001
        assert session.state == FlowState.AGENTIC.value

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

    async def test_create_missing_accepts_frontend_uuid(self) -> None:
        """D-04：/runs 传入前端新生成的 id 时按该 id 建容器并开轮。"""
        store = FakeStore()
        session = await start_turn(store, "local", "frontend-uuid", create_missing=True)
        assert session.session_id == "frontend-uuid"
        assert session.state == FlowState.INIT.value
        assert store.items["frontend-uuid"].user_id == "local"

    async def test_create_missing_keeps_other_user_rejected(self) -> None:
        store = FakeStore()
        store.items["s9"] = FlowSession(
            session_id="s9", user_id="someone-else", state=FlowState.DONE.value
        )
        with pytest.raises(StateError) as caught:
            await start_turn(store, "local", "s9", create_missing=True)
        assert caught.value.code == 6003
