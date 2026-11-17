"""回放比较：单 Trace 自比对 / 双 Trace 版本对比。"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

from devprompt_ai.domain.obs.contract.query import ReplayNodeResult
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceKind, canonical_json
from devprompt_ai.domain.obs.replay.normalize import diff_values, normalize_snapshot

#: 参与节点比对的 kind（请求事件不单独比对，结果事件承载输出）。
_COMPARE_KINDS = frozenset(
    {
        TraceKind.ACTION_END.value,
        TraceKind.LLM_RESULT.value,
        TraceKind.TOOL_RESULT.value,
        TraceKind.DECISION_RESULT.value,
        TraceKind.FILE.value,
        TraceKind.SYMBOLS.value,
        TraceKind.GATE.value,
        TraceKind.SENSORIUM.value,
    }
)


def _node_key(event: TraceEvent) -> tuple[str, str, str] | None:
    """并发节点的对齐键：有 call_key 按 (kind, name, call_key) 对齐，否则按位置。"""
    call_key = str(event.attributes.get("call_key", ""))
    return (event.kind, event.name, call_key) if call_key else None


def _missing_node(exp: TraceEvent | None, act: TraceEvent | None) -> ReplayNodeResult:
    present = exp or act
    return ReplayNodeResult(
        seq=present.seq if present is not None else 0,
        kind=present.kind if present is not None else "",
        name=present.name if present is not None else "",
        match=False,
        expected=exp.to_payload(full=True) if exp is not None else {},
        actual=act.to_payload(full=True) if act is not None else {},
        diff={"missing": "expected" if exp is None else "actual"},
    )


def _compare_pair(exp: TraceEvent, act: TraceEvent) -> ReplayNodeResult:
    same_kind = exp.kind == act.kind and exp.name == act.name
    exp_out = normalize_snapshot({"value": exp.output}).get("value", exp.output)
    act_out = normalize_snapshot({"value": act.output}).get("value", act.output)
    diffs = diff_values(exp_out, act_out)
    match = same_kind and not diffs
    return ReplayNodeResult(
        seq=act.seq,
        kind=act.kind,
        name=act.name,
        match=match,
        expected=exp_out,
        actual=act_out,
        diff={"diffs": diffs} if diffs else ({} if same_kind else {"kind_mismatch": True}),
    )


def compare_streams(
    expected: Sequence[TraceEvent], actual: Sequence[TraceEvent]
) -> list[ReplayNodeResult]:
    """比较两条事件流：并发节点按 call_key 对齐，顺序节点按位置对齐。

    真实运行的 ``verify_facts`` 用 ``asyncio.gather`` 并发取证，事件 seq 取决于完成
    顺序；回放时完成顺序不同会导致 ``file.read``/``exists`` 错位。故有 call_key 的
    节点按 ``(kind, name, call_key)`` 配对（D-07），只有无 key 的顺序节点才按位置比。
    """
    left = [event for event in expected if event.kind in _COMPARE_KINDS]
    right = [event for event in actual if event.kind in _COMPARE_KINDS]
    nodes: list[ReplayNodeResult] = []

    right_by_key: dict[tuple[str, str, str], deque[tuple[int, TraceEvent]]] = defaultdict(deque)
    for index, event in enumerate(right):
        key = _node_key(event)
        if key is not None:
            right_by_key[key].append((index, event))
    consumed: set[int] = set()
    unkeyed_left: list[TraceEvent] = []

    for exp in left:
        key = _node_key(exp)
        if key is None:
            unkeyed_left.append(exp)
            continue
        queue = right_by_key.get(key)
        if queue:
            index, act = queue.popleft()
            consumed.add(index)
            nodes.append(_compare_pair(exp, act))
        else:
            nodes.append(_missing_node(exp, None))

    unkeyed_right: list[TraceEvent] = []
    for index, event in enumerate(right):
        if index in consumed:
            continue
        if _node_key(event) is None:
            unkeyed_right.append(event)
        else:
            nodes.append(_missing_node(None, event))

    for index in range(max(len(unkeyed_left), len(unkeyed_right))):
        left_event = unkeyed_left[index] if index < len(unkeyed_left) else None
        right_event = unkeyed_right[index] if index < len(unkeyed_right) else None
        nodes.append(
            _compare_pair(left_event, right_event)
            if left_event is not None and right_event is not None
            else _missing_node(left_event, right_event)
        )
    return nodes


def compare_snapshots(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    left = normalize_snapshot(expected)
    right = normalize_snapshot(actual)
    diffs = diff_values(left, right)
    return {
        "match": not diffs,
        "expected": left,
        "actual": right,
        "diffs": diffs,
        "expected_hash": canonical_json(left),
        "actual_hash": canonical_json(right),
    }


def compare_two_traces(
    left: Sequence[TraceEvent], right: Sequence[TraceEvent]
) -> tuple[list[ReplayNodeResult], dict[str, Any]]:
    """双 Trace 版本对比：节点流 + 最终快照。"""
    left_snapshot = final_snapshot(left)
    right_snapshot = final_snapshot(right)
    nodes = compare_streams(left, right)
    final = compare_snapshots(left_snapshot, right_snapshot)
    return nodes, final


def final_snapshot(events: Sequence[TraceEvent]) -> dict[str, Any]:
    for event in reversed(events):
        if event.kind == TraceKind.TURN_END.value:
            snapshot = event.output.get("snapshot")
            return snapshot if isinstance(snapshot, dict) else event.output
    return {}
