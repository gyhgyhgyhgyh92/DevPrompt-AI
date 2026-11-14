"""Trace 调用链树与预览测试。"""

from __future__ import annotations

from devprompt_ai.domain.obs.contract.trace import TraceEvent
from devprompt_ai.domain.obs.trace.tree import build_tree, flatten_preview


def _event(event_id: str, seq: int, parent: str = "", *, output: dict | None = None) -> TraceEvent:
    return TraceEvent(
        event_id=event_id,
        trace_id="t1",
        session_id="s1",
        turn_id="turn1",
        turn_index=0,
        run_id="r1",
        seq=seq,
        parent_id=parent,
        kind="action.start" if parent == "" else "llm.response",
        name="retrieve" if parent == "" else "generate_single",
        status="ok",
        started_at="2026-11-12T10:00:00.000Z",
        ended_at="2026-11-12T10:00:01.000Z",
        duration_ms=10,
        output=output or {},
    )


def test_build_tree_nests_by_parent_id() -> None:
    root = _event("e1", 1)
    child = _event("e2", 2, "e1")

    tree = build_tree([child, root])

    assert len(tree) == 1
    assert tree[0]["event_id"] == "e1"
    assert [item["event_id"] for item in tree[0]["children"]] == ["e2"]


def test_orphan_event_becomes_root() -> None:
    tree = build_tree([_event("e2", 2, "missing")])

    assert [item["event_id"] for item in tree] == ["e2"]


def test_preview_truncates_large_payload() -> None:
    event = _event("e1", 1, output={"text": "x" * 2000})

    payload = flatten_preview([event], limit=100)[0]

    assert payload["output_preview"]["truncated"] is True
    assert len(payload["output_preview"]["preview"]) == 100
    assert payload["output"] == payload["output_preview"]
