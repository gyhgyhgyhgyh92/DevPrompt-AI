"""运行时层存储测试：事件 seq、运行状态、第一应答获胜、工件与仓库图。"""

from __future__ import annotations

from pathlib import Path

import pytest

from devprompt_ai.memory.artifact_store import SQLiteArtifactStore
from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.memory.intervention_store import SQLiteInterventionStore
from devprompt_ai.memory.repo_index import SQLiteRepoIndex
from devprompt_ai.memory.routing_stats import SQLiteRoutingStats
from devprompt_ai.memory.run_store import SQLiteRunStore
from devprompt_ai.memory.token_ledger import SQLiteTokenLedger


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


async def test_event_seq_is_monotonic_per_session(tmp_path: Path) -> None:
    store = SQLiteEventStore(_db(tmp_path))

    first = await store.append("s1", "thought", {"text": "a"})
    second = await store.append("s1", "action", {"title": "b"})
    other = await store.append("s2", "thought", {"text": "c"})

    assert (first.seq, second.seq) == (1, 2)
    assert other.seq == 1, "seq 按会话独立分配"
    assert await store.last_seq("s1") == 2


async def test_event_since_and_before(tmp_path: Path) -> None:
    store = SQLiteEventStore(_db(tmp_path))
    for i in range(5):
        await store.append("s1", "thought", {"i": i})

    after = await store.since("s1", 2)
    before = await store.before("s1", 4, limit=2)

    assert [e.seq for e in after] == [3, 4, 5]
    assert [e.seq for e in before] == [2, 3], "before 返回最近的更早事件且升序"
    assert await store.since("s1", 99) == []


async def test_event_payload_roundtrip(tmp_path: Path) -> None:
    store = SQLiteEventStore(_db(tmp_path))
    await store.append("s1", "snapshot", {"nested": {"k": [1, 2]}}, run_id="r1")

    events = await store.since("s1", 0)

    assert events[0].payload == {"nested": {"k": [1, 2]}}
    assert events[0].run_id == "r1"
    assert events[0].to_wire()["seq"] == 1


async def test_run_lifecycle(tmp_path: Path) -> None:
    store = SQLiteRunStore(_db(tmp_path))
    await store.create(run_id="r1", session_id="s1", turn_index=0, request_id="req")

    running = await store.get("r1")
    assert running is not None
    assert running.status == "running"
    assert running.is_terminal is False

    await store.finish("r1", "done", stop_reason="natural-finish")
    finished = await store.get("r1")
    assert finished is not None
    assert finished.status == "done"
    assert finished.stop_reason == "natural-finish"
    assert finished.ended_at
    assert finished.is_terminal is True

    with pytest.raises(ValueError):
        await store.finish("r1", "running")


async def test_run_orphans_are_aborted(tmp_path: Path) -> None:
    import sqlite3

    path = _db(tmp_path)
    store = SQLiteRunStore(path)
    await store.create(run_id="r1", session_id="s1", turn_index=0)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE runs SET started_at = '2000-01-01T00:00:00.000Z'")

    assert await store.mark_orphans_aborted(older_than_minutes=30) == 1
    record = await store.get("r1")
    assert record is not None
    assert record.status == "aborted"
    assert record.stop_reason == "process-restart"


async def test_intervention_first_answer_wins(tmp_path: Path) -> None:
    store = SQLiteInterventionStore(_db(tmp_path))
    item = await store.register("s1", kind="approval", payload={"tool": "write_file"})

    assert await store.resolve(item.request_id, "approve") is True
    assert await store.resolve(item.request_id, "deny") is False, "第二应答必须失败"
    resolved = await store.get(item.request_id)
    assert resolved is not None
    assert resolved.decision == "approve"
    assert resolved.status == "resolved"


async def test_intervention_rejects_unknown_decision(tmp_path: Path) -> None:
    store = SQLiteInterventionStore(_db(tmp_path))
    item = await store.register("s1")

    with pytest.raises(ValueError):
        await store.resolve(item.request_id, "yes")


async def test_intervention_pending_and_cancel(tmp_path: Path) -> None:
    store = SQLiteInterventionStore(_db(tmp_path))
    first = await store.register("s1")
    await store.register("s1")

    assert len(await store.pending("s1")) == 2
    assert await store.cancel_pending("s1") == 2
    assert await store.pending("s1") == []
    assert await store.resolve(first.request_id, "answer") is False, "已取消不能再裁决"


async def test_artifact_roundtrip(tmp_path: Path) -> None:
    store = SQLiteArtifactStore(_db(tmp_path))
    artifact_id = await store.put(
        "正文内容", kind="discarded_history", session_id="s1", meta={"reason": "compact"}
    )

    assert await store.get(artifact_id) == "正文内容"
    assert await store.get_meta(artifact_id) == {"reason": "compact"}
    assert await store.get("missing") is None


async def test_token_ledger_totals(tmp_path: Path) -> None:
    ledger = SQLiteTokenLedger(_db(tmp_path))
    await ledger.record(session_id="s1", prompt_tokens=10, completion_tokens=5, cached_tokens=2)
    await ledger.record(session_id="s1", prompt_tokens=20, completion_tokens=7)

    assert await ledger.totals("s1") == {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "cached_tokens": 2,
    }
    assert (await ledger.totals("missing"))["prompt_tokens"] == 0


async def test_routing_stats_accumulate(tmp_path: Path) -> None:
    stats = SQLiteRoutingStats(_db(tmp_path))
    await stats.record(model_id="m1", task_kind="probe", success=True, latency_ms=100)
    await stats.record(model_id="m1", task_kind="probe", success=False, latency_ms=300)

    assert await stats.load_all() == {("m1", "probe"): (2, 1, 400)}


async def test_repo_index_reverse_dependents(tmp_path: Path) -> None:
    index = SQLiteRepoIndex(_db(tmp_path))
    await index.replace_file("proj", "a.py", [("f", "function", 1, 2, "f()")], [])
    await index.replace_file("proj", "b.py", [], [("a.py", "import", "")])
    await index.replace_file("proj", "c.py", [], [("b.py", "import", "")])

    direct = await index.reverse_dependents("proj", "a.py", max_hops=1)
    full = await index.reverse_dependents("proj", "a.py", max_hops=3)

    assert direct == {"b.py": 1}
    assert full == {"b.py": 1, "c.py": 2}


async def test_repo_index_replace_removes_stale(tmp_path: Path) -> None:
    index = SQLiteRepoIndex(_db(tmp_path))
    await index.replace_file("proj", "a.py", [("old", "function", 1, 2, "")], [])
    await index.replace_file("proj", "a.py", [("new", "function", 3, 4, "")], [])

    assert await index.symbols_named("proj", "old") == []
    assert await index.symbols_named("proj", "new") == [("a.py", "function", 3)]


async def test_event_checksum_verifies_and_detects_tamper(tmp_path: Path) -> None:
    """阶段7：写入即算校验和；篡改行在启动校验中暴露（只告警不删改）。"""
    import sqlite3

    store = SQLiteEventStore(_db(tmp_path))
    await store.init_schema()
    await store.append("s1", "thought", {"text": "a"})

    assert await store.verify_checksums() == 0

    with sqlite3.connect(_db(tmp_path)) as conn:
        conn.execute('UPDATE run_events SET payload = \'{"text": "篡改"}\' WHERE seq = 1')

    assert await store.verify_checksums() == 1


async def test_event_schema_migration_adds_checksum(tmp_path: Path) -> None:
    """旧库升级：无 checksum 列的 run_events 由 init_schema 补列，写入不炸。"""
    import sqlite3

    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE run_events ("
            " session_id TEXT NOT NULL, seq INTEGER NOT NULL, run_id TEXT NOT NULL DEFAULT '',"
            " type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',"
            " created_at TEXT NOT NULL DEFAULT '', PRIMARY KEY (session_id, seq))"
        )

    store = SQLiteEventStore(db)
    await store.init_schema()
    event = await store.append("s1", "thought", {"text": "a"})

    assert event.seq == 1
    assert await store.verify_checksums() == 0
