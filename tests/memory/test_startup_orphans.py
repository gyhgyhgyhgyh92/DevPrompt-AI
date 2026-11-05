"""启动期孤儿 turn 扫描（2026-11-04）。

进程在 agentic 循环里被强杀会留下「turn 停在 AGENTIC / 会话停在活跃态」的组合，
此后 start_turn 会一直拒绝（6001）。这里锁死四条行为：超时收尾、未超时不动、
终态不动、会话版本号自增。
"""

from __future__ import annotations

import sqlite3

import pytest

from devprompt_ai.memory.schema import SESSIONS_DDL, TURNS_DDL
from devprompt_ai.memory.startup_safety_check import _abort_orphan_turns


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SESSIONS_DDL)
    connection.executescript(TURNS_DDL)
    return connection


def _insert_turn(
    conn: sqlite3.Connection, *, turn_id: str, session_id: str, state: str, age: str
) -> None:
    conn.execute(
        "INSERT INTO forge_turns (turn_id, session_id, turn_index, state, input, created_at) "
        "VALUES (?, ?, 0, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now', ?))",
        (turn_id, session_id, state, "句子", age),
    )


def _insert_session(conn: sqlite3.Connection, *, session_id: str, state: str) -> None:
    conn.execute(
        "INSERT INTO forge_sessions (session_id, user_id, state, version, payload) "
        "VALUES (?, 'local', ?, 3, '{}')",
        (session_id, state),
    )


def _state_of(conn: sqlite3.Connection, table: str, key: str, value: str) -> str:
    row = conn.execute(f"SELECT state FROM {table} WHERE {key} = ?", (value,)).fetchone()
    assert row is not None
    return str(row[0])


def test_stale_agentic_turn_is_aborted(conn: sqlite3.Connection) -> None:
    _insert_session(conn, session_id="s-old", state="AGENTIC")
    _insert_turn(conn, turn_id="t-old", session_id="s-old", state="AGENTIC", age="-40 minutes")

    affected = _abort_orphan_turns(conn)

    assert affected == 1
    assert _state_of(conn, "forge_turns", "turn_id", "t-old") == "ABORTED"
    assert _state_of(conn, "forge_sessions", "session_id", "s-old") == "ABORTED"


def test_fresh_turn_is_left_alone(conn: sqlite3.Connection) -> None:
    """一分钟前的 turn 可能正在跑，不能被误杀。"""
    _insert_session(conn, session_id="s-new", state="AGENTIC")
    _insert_turn(conn, turn_id="t-new", session_id="s-new", state="AGENTIC", age="-1 minutes")

    assert _abort_orphan_turns(conn) == 0
    assert _state_of(conn, "forge_turns", "turn_id", "t-new") == "AGENTIC"
    assert _state_of(conn, "forge_sessions", "session_id", "s-new") == "AGENTIC"


def test_terminal_turn_is_untouched(conn: sqlite3.Connection) -> None:
    _insert_session(conn, session_id="s-done", state="DONE")
    _insert_turn(conn, turn_id="t-done", session_id="s-done", state="DONE", age="-90 minutes")

    assert _abort_orphan_turns(conn) == 0
    assert _state_of(conn, "forge_turns", "turn_id", "t-done") == "DONE"
    assert _state_of(conn, "forge_sessions", "session_id", "s-done") == "DONE"


def test_session_version_bumps_so_later_cas_does_not_conflict(conn: sqlite3.Connection) -> None:
    _insert_session(conn, session_id="s-bump", state="GENERATING")
    _insert_turn(conn, turn_id="t-bump", session_id="s-bump", state="INIT", age="-45 minutes")

    _abort_orphan_turns(conn)

    row = conn.execute(
        "SELECT state, version FROM forge_sessions WHERE session_id = 's-bump'"
    ).fetchone()
    assert row is not None
    assert row[0] == "ABORTED"
    assert row[1] == 4  # 原 version 3 + 1


def test_asking_session_is_not_treated_as_orphan(conn: sqlite3.Connection) -> None:
    """ASKING 是等用户，不是执行中：即便 turn 很旧也不能被收尾。"""
    _insert_session(conn, session_id="s-ask", state="ASKING")
    _insert_turn(conn, turn_id="t-ask", session_id="s-ask", state="INIT", age="-120 minutes")

    assert _abort_orphan_turns(conn) == 0
    assert _state_of(conn, "forge_sessions", "session_id", "s-ask") == "ASKING"
