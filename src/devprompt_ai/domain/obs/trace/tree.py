"""调用链树构建与列表预览（纯函数）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from devprompt_ai.domain.obs.contract.trace import TraceEvent, preview


def build_tree(events: Sequence[TraceEvent], *, full: bool = False) -> list[dict[str, Any]]:
    """按 parent_id 组装树；找不到父节点的事件作为根返回（不丢数据）。"""
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in sorted(events, key=lambda item: item.seq):
        node = event.to_payload(full=full)
        node["children"] = []
        nodes[event.event_id] = node
        order.append(event.event_id)
    roots: list[dict[str, Any]] = []
    for event_id in order:
        node = nodes[event_id]
        parent_id = node.get("parent_id", "")
        parent = nodes.get(parent_id) if parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def flatten_preview(events: Sequence[TraceEvent], *, limit: int = 500) -> list[dict[str, Any]]:
    """列表页轻量投影：input/output 只给 preview，避免大 payload 传输。"""
    out: list[dict[str, Any]] = []
    for event in events:
        payload = event.to_payload(full=False)
        truncated_input = preview(event.input, limit)
        truncated_output = preview(event.output, limit)
        payload["input"] = truncated_input
        payload["output"] = truncated_output
        payload["input_preview"] = truncated_input
        payload["output_preview"] = truncated_output
        out.append(payload)
    return out
