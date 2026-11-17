"""回放比较：快照归一化与结构化 diff（纯函数）。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.obs.contract.trace import canonical_json

#: 比较时保留的业务字段（去掉时间、随机 ID、过程文本）。
_SNAPSHOT_KEYS = (
    "status",
    "state",
    "target",
    "variant",
    "reply_text",
    "facts",
    "facts_complete",
    "claim_report",
    "delivery_gate",
    "anchor_report",
    "evidence_stale",
)

_MAX_DIFFS = 50


def normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """只保留可比较的业务字段；集合类字段按稳定 JSON 排序。"""
    out: dict[str, Any] = {}
    for key in _SNAPSHOT_KEYS:
        if key not in snapshot:
            continue
        value = snapshot[key]
        if key == "facts" and isinstance(value, list):
            value = sorted(value, key=canonical_json)
        if key == "variant" and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in {"fallback"}}
        out[key] = value
    return out


def diff_values(
    expected: Any,
    actual: Any,
    *,
    path: str = "",
    limit: int = _MAX_DIFFS,
) -> list[dict[str, Any]]:
    """返回前 ``limit`` 条差异；类型不同时记一条整值差异。"""
    diffs: list[dict[str, Any]] = []

    def _walk(left: Any, right: Any, current: str) -> None:
        if len(diffs) >= limit:
            return
        if type(left) is not type(right):
            diffs.append({"path": current, "expected": left, "actual": right})
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                _walk(left.get(key), right.get(key), f"{current}.{key}" if current else key)
            return
        if isinstance(left, list):
            if len(left) != len(right):
                diffs.append(
                    {"path": f"{current}.length", "expected": len(left), "actual": len(right)}
                )
            for index, (l_item, r_item) in enumerate(zip(left, right, strict=False)):
                _walk(l_item, r_item, f"{current}[{index}]")
            return
        if left != right:
            diffs.append({"path": current, "expected": left, "actual": right})

    _walk(expected, actual, path)
    return diffs
