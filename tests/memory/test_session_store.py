"""SQLiteSessionStore 集成测试：本地临时库，无外部依赖。"""

import pytest

from devprompt_ai.domain.models import FlowSession
from devprompt_ai.memory.session_store import SQLiteSessionStore
from devprompt_ai.state import FlowState, transition


@pytest.fixture()
def store(tmp_path):  # type: ignore[no-untyped-def]
    return SQLiteSessionStore(str(tmp_path / "test.db"))


async def test_init_schema_idempotent_and_wal(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    await store.init_schema()  # 幂等复跑
    import sqlite3

    conn = sqlite3.connect(store._db_path)  # noqa: SLF001 —— 测试断言内部路径
    row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row is not None and row[0] == "wal"
    conn.close()


async def test_create_load_save_cas_cycle(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    session = FlowSession(
        session_id="it-case-1",
        user_id="local",
        state=FlowState.INIT.value,
        data={"sentence": "测试"},
    )
    await store.create(session)
    loaded = await store.load("it-case-1")
    assert loaded is not None and loaded.data["sentence"] == "测试"
    assert await store.save(loaded) is True
    assert loaded.version == 1
    again = await store.load("it-case-1")
    assert again is not None
    await transition(again, FlowState.RETRIEVING, store)
    final = await store.load("it-case-1")
    assert final is not None and final.state == "RETRIEVING"


async def test_load_missing_returns_none(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    assert await store.load("missing") is None


async def test_cas_conflict_detected(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    b = FlowSession(session_id="it-case-2", user_id="local", state=FlowState.RETRIEVING.value)
    await store.create(b)
    assert await store.save(b) is True  # 另一写入者推进版本 0→1
    stale = FlowSession(
        session_id="it-case-2", user_id="local", state=FlowState.PROBING.value, version=0
    )  # 持旧版本的并发副本
    assert await store.save(stale) is False  # 版本过期 → False（调用方转 6001）
