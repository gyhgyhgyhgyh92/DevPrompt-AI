"""Replay 比较与归一化测试。"""

from __future__ import annotations

from devprompt_ai.domain.obs.contract.trace import TraceEvent
from devprompt_ai.domain.obs.replay.compare import compare_snapshots, compare_streams
from devprompt_ai.domain.obs.replay.normalize import diff_values, normalize_snapshot


def _event(seq: int, kind: str, name: str, output: dict, *, call_key: str = "") -> TraceEvent:
    return TraceEvent(
        event_id=f"e{seq}",
        trace_id="t1",
        session_id="s1",
        turn_id="turn1",
        turn_index=0,
        run_id="r1",
        seq=seq,
        parent_id="",
        kind=kind,
        name=name,
        status="ok",
        started_at="2026-11-12T10:00:00.000Z",
        ended_at="2026-11-12T10:00:01.000Z",
        duration_ms=1,
        output=output,
        attributes={"call_key": call_key} if call_key else {},
    )


def test_normalize_snapshot_drops_volatile_fields() -> None:
    normalized = normalize_snapshot(
        {
            "status": "done",
            "state": "DONE",
            "variant": {"title": "t", "body": "b", "fallback": True},
            "internal": {"started_at": 1},
        }
    )

    assert normalized["status"] == "done"
    assert "fallback" not in normalized["variant"]
    assert "internal" not in normalized


def test_diff_values_reports_paths() -> None:
    diffs = diff_values({"a": 1, "b": [1, 2]}, {"a": 2, "b": [1, 3]})

    assert {item["path"] for item in diffs} == {"a", "b[1]"}


def test_compare_streams_flags_mismatch_and_missing() -> None:
    left = [_event(1, "action.end", "retrieve", {"status": "ok"})]
    right = [
        _event(1, "action.end", "retrieve", {"status": "failed"}),
        _event(2, "action.end", "probe", {}),
    ]

    nodes = compare_streams(left, right)

    assert len(nodes) == 2
    assert nodes[0].match is False
    assert "diffs" in nodes[0].diff
    assert "missing" in nodes[1].diff


def test_compare_streams_aligns_concurrent_nodes_by_call_key() -> None:
    """D-07：并发完成顺序不同（read/exists 互换）仍应全部 match。"""
    left = [
        _event(1, "file.read", "read", {"content": "a"}, call_key="file:a"),
        _event(2, "file.read", "exists", {"exists": True}, call_key="exists:a"),
    ]
    right = [
        _event(1, "file.read", "exists", {"exists": True}, call_key="exists:a"),
        _event(2, "file.read", "read", {"content": "a"}, call_key="file:a"),
    ]

    nodes = compare_streams(left, right)

    assert len(nodes) == 2
    assert all(node.match for node in nodes)


def test_compare_streams_reports_missing_keyed_node() -> None:
    left = [_event(1, "tool.result", "command", {"stdout": "x"}, call_key="tool:x")]
    right = [_event(1, "tool.result", "command", {"stdout": "y"}, call_key="tool:y")]

    nodes = compare_streams(left, right)

    assert len(nodes) == 2
    assert {node.diff.get("missing") for node in nodes} == {"actual", "expected"}
    assert all(node.match is False for node in nodes)


def test_compare_snapshots_ignores_fallback_flag() -> None:
    left = {"status": "done", "variant": {"title": "t", "fallback": False}}
    right = {"status": "done", "variant": {"title": "t", "fallback": True}}

    assert compare_snapshots(left, right)["match"] is True
