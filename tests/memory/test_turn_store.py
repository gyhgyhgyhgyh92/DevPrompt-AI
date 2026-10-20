"""多轮 turn 存储（2026-10-20）：append-only、按 index 排序、唯一索引即乐观锁。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from devprompt_ai.domain.models import TurnRecord
from devprompt_ai.memory.turn_store import SQLiteTurnStore, TurnConflictError


def _turn(
    turn_id: str,
    index: int,
    *,
    session_id: str = "s1",
    facts: list[dict[str, Any]] | None = None,
    clarifications: dict[str, str] | None = None,
    output: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> TurnRecord:
    return TurnRecord(
        turn_id=turn_id,
        session_id=session_id,
        turn_index=index,
        state="DONE",
        input=f"第 {index} 轮",
        facts=facts or [],
        clarifications=clarifications or {},
        output=output or [],
        summary=summary or {},
        usage=usage or {},
    )


def _store(tmp_path: Path) -> SQLiteTurnStore:
    return SQLiteTurnStore(str(tmp_path / "turns.db"))


async def test_append_then_list_is_ordered_by_index(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.append(_turn("t2", 1))
    await store.append(_turn("t1", 0))

    turns = await store.list_for_session("s1")

    assert [t.turn_index for t in turns] == [0, 1]
    assert [t.turn_id for t in turns] == ["t1", "t2"]


async def test_payload_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.append(
        _turn(
            "t1",
            0,
            facts=[{"key": "token_defined", "passed": False, "evidence": "未找到"}],
            clarifications={"scope": "只改这一处"},
            output=[{"level": "A", "body": "改按钮"}],
            summary={"target": "Button"},
            usage={"llm_tokens": 1234},
        )
    )

    loaded = await store.load("t1")

    assert loaded is not None
    assert loaded.facts[0]["key"] == "token_defined"
    assert loaded.clarifications == {"scope": "只改这一处"}
    assert loaded.output[0]["body"] == "改按钮"
    assert loaded.summary == {"target": "Button"}
    assert loaded.usage == {"llm_tokens": 1234}
    assert loaded.created_at  # DB 默认值已写入


async def test_duplicate_session_index_is_rejected(tmp_path: Path) -> None:
    """唯一索引即乐观锁：重复提交在 DB 层被拒，不依赖前端防抖（MUST-15）。"""
    store = _store(tmp_path)
    await store.append(_turn("t1", 0))

    with pytest.raises(TurnConflictError):
        await store.append(_turn("t2", 0))


async def test_same_index_allowed_across_sessions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.append(_turn("a1", 0, session_id="a"))
    await store.append(_turn("b1", 0, session_id="b"))

    assert len(await store.list_for_session("a")) == 1
    assert len(await store.list_for_session("b")) == 1


async def test_list_isolated_per_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.append(_turn("a1", 0, session_id="a"))
    await store.append(_turn("b1", 0, session_id="b"))

    turns = await store.list_for_session("a")

    assert [t.session_id for t in turns] == ["a"]


async def test_missing_turn_returns_none(tmp_path: Path) -> None:
    assert await _store(tmp_path).load("nope") is None
