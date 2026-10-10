"""SQLitePreferenceStore 集成测试：tmp_path 真实 SQLite，无外部依赖。"""

from pathlib import Path

import pytest

from devprompt_ai.domain.ranking.ports import AdoptionRecord, PreferenceStore, VariantLevel
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.memory.preference_store import SQLitePreferenceStore


@pytest.fixture()
def store(tmp_path: Path) -> SQLitePreferenceStore:
    return SQLitePreferenceStore(str(tmp_path / "pref.db"))


def _rec(
    variant: VariantLevel = "C",
    *,
    user_id: str = "u1",
    session_id: str = "s1",
    edited: bool = False,
    ratio: float = 0.0,
) -> AdoptionRecord:
    return AdoptionRecord(
        user_id=user_id,
        session_id=session_id,
        variant=variant,
        edited=edited,
        edited_text_ratio=ratio,
        features={
            "detail_level": {"A": 0.3, "B": 0.6, "C": 0.9}[variant],
            "include_diff": {"A": 0.5, "B": 0.8, "C": 0.9}[variant],
            "specify_tests": {"A": 0.2, "B": 0.5, "C": 0.8}[variant],
            "max_files_norm": {"A": 0.25, "B": 0.58, "C": 1.0}[variant],
        },
    )


async def test_init_schema_idempotent_and_wal(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    await store.init_schema()  # 幂等复跑
    import sqlite3

    conn = sqlite3.connect(store._db_path)  # noqa: SLF001 —— 测试断言内部路径
    mode = conn.execute("PRAGMA journal_mode").fetchone()
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN"
            " ('preference_vectors','adoption_history')"
        ).fetchall()
    }
    conn.close()
    assert mode is not None and mode[0] == "wal"
    assert tables == {"preference_vectors", "adoption_history"}


async def test_load_missing_returns_initial_preference(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    assert await store.load("nobody") == dict(INITIAL_PREFERENCE)


async def test_save_load_roundtrip_and_upsert(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    v1 = {"detail_level": 0.7, "include_diff": 0.2, "specify_tests": 0.9, "max_files_norm": 1.0}
    await store.save("u1", v1)
    assert await store.load("u1") == v1
    v2 = {"detail_level": 0.54, "include_diff": 0.54, "specify_tests": 0.53, "max_files_norm": 0.55}
    await store.save("u1", v2)  # UPSERT 覆盖
    assert await store.load("u1") == v2


async def test_record_adoption_and_history_roundtrip(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    await store.record_adoption(_rec("C"))
    await store.record_adoption(_rec("B", edited=True, ratio=0.4, session_id="s2"))
    hist = await store.history("u1")
    assert len(hist) == 2
    assert hist[0].variant == "B" and hist[0].session_id == "s2"  # 最新在前
    assert hist[0].edited is True and hist[0].edited_text_ratio == pytest.approx(0.4)
    assert hist[0].features == _rec("B").features  # features_json 往返一致
    assert hist[1].variant == "C" and hist[1].edited is False


async def test_history_limit_and_user_partition(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    await store.record_adoption(_rec("A", session_id="s1"))
    await store.record_adoption(_rec("C", session_id="s2"))
    await store.record_adoption(_rec("B", user_id="u2", session_id="s3"))
    assert len(await store.history("u1", limit=1)) == 1  # limit 生效
    hist_u1 = await store.history("u1")
    assert [r.session_id for r in hist_u1] == ["s2", "s1"]  # 仅本 user 分区，最新在前
    hist_u2 = await store.history("u2")
    assert [r.variant for r in hist_u2] == ["B"]


async def test_store_satisfies_preference_store_protocol(store: SQLitePreferenceStore) -> None:
    await store.init_schema()
    assert issubclass(SQLitePreferenceStore, PreferenceStore)  # runtime_checkable 契约
    # Protocol 三方法真实可调用（非仅鸭子签名）
    await store.save("u1", dict(INITIAL_PREFERENCE))
    await store.record_adoption(_rec("C"))
    assert (await store.load("u1"))["detail_level"] == pytest.approx(0.5)
    assert len(await store.history("u1")) == 1
