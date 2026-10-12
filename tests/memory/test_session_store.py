"""SQLiteSessionStore 集成测试：本地临时库，无外部依赖。"""

import sqlite3

import pytest

from devprompt_ai.domain.models import FlowSession
from devprompt_ai.memory.session_store import SQLiteSessionStore
from devprompt_ai.state import FlowState, transition


@pytest.fixture()
def store(tmp_path):  # type: ignore[no-untyped-def]
    return SQLiteSessionStore(str(tmp_path / "test.db"))


def _set_updated_at(store: SQLiteSessionStore, session_id: str, ts: str) -> None:
    """确定性覆盖 updated_at（create 恒取当前时间，无法注入历史时刻）。"""
    conn = sqlite3.connect(store._db_path)
    try:
        conn.execute(
            "UPDATE forge_sessions SET updated_at = ? WHERE session_id = ?", (ts, session_id)
        )
        conn.commit()
    finally:
        conn.close()


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


# ---- Task 1：会话摘要 title/pinned 与 delete（T1.1） ----


async def _create(store, session_id: str, **data) -> None:  # type: ignore[no-untyped-def]
    await store.create(
        FlowSession(
            session_id=session_id,
            user_id="local",
            state=FlowState.DONE.value,
            data=dict(data),
        )
    )


async def test_list_recent_truncates_title(store) -> None:  # type: ignore[no-untyped-def]
    """无 custom_title → 原句 strip 后截断 ≤40。"""
    await store.init_schema()
    long_sentence = "把提交按钮改成 primary-500 并补充单元测试覆盖边界情况以及额外说明文字"
    await _create(store, "t1", sentence=long_sentence)
    items = await store.list_recent("local")
    assert len(items) == 1
    assert items[0].title == long_sentence.strip()[:40]
    assert len(items[0].title) == 40


async def test_list_recent_prefers_custom_title(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    await _create(store, "t2", sentence="原句标题", custom_title="自定义标题")
    items = await store.list_recent("local")
    assert items[0].title == "自定义标题"


async def test_list_recent_pins_first(store) -> None:  # type: ignore[no-untyped-def]
    """pinned 优先于 updated_at 倒序：置顶的旧会话须排在未置顶的新会话之前。"""
    await store.init_schema()
    await _create(store, "old", sentence="旧会话")
    await _create(store, "new", sentence="新会话")
    _set_updated_at(store, "old", "2020-01-01T00:00:00.000Z")
    _set_updated_at(store, "new", "2030-01-01T00:00:00.000Z")
    # 未置顶：updated_at 倒序 → new 在前
    assert [s.session_id for s in await store.list_recent("local")] == ["new", "old"]
    # 置顶 old：即使时间更旧也排前
    session = await store.load("old")
    assert session is not None
    session.data["pinned"] = True
    assert await store.save(session) is True
    pinned = await store.list_recent("local")
    assert [s.session_id for s in pinned] == ["old", "new"]
    assert pinned[0].pinned is True


async def test_delete_is_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    await store.init_schema()
    await _create(store, "del-1", sentence="待删")
    assert await store.delete("del-1") is True
    assert await store.load("del-1") is None
    assert await store.delete("del-1") is False  # 二次删除不报错（幂等）


async def test_rename_and_pin_persist(store) -> None:  # type: ignore[no-untyped-def]
    """service.rename_session / pin_session 的落库路径 = load → 改 payload → save，摘要须反映。"""
    await store.init_schema()
    await _create(store, "rp-1", sentence="原句")
    session = await store.load("rp-1")
    assert session is not None
    session.data["custom_title"] = "重命名标题"
    assert await store.save(session) is True
    session2 = await store.load("rp-1")
    assert session2 is not None
    session2.data["pinned"] = True
    assert await store.save(session2) is True
    items = await store.list_recent("local")
    assert items[0].title == "重命名标题"
    assert items[0].pinned is True
