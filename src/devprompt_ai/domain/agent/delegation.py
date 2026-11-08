"""委派调度策略（K2、K5）：去重、冲突、可运行性与失败降级。

失败降级链：解析成功 → ok；解析失败但能打捞 → partial 且**强制标未验证**；
完全打捞不出 → blocked。打捞结果不许冒充成功。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from devprompt_ai.domain.agent.work_order import WorkOrder, dedupe_key


@dataclass(frozen=True, slots=True)
class WorkerResult:
    status: Literal["ok", "partial", "blocked"]
    output: str = ""
    evidence: tuple[str, ...] = ()
    salvaged: bool = False
    evidence_status: Literal["verified", "unverified"] = "verified"


def plan_orders(orders: Sequence[WorkOrder]) -> list[WorkOrder]:
    """按去重键保留首个；顺序不变。"""
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    planned: list[WorkOrder] = []
    for order in orders:
        key = dedupe_key(order)
        if key in seen:
            continue
        seen.add(key)
        planned.append(order)
    return planned


def conflicts(inflight: Iterable[str], files: Iterable[str]) -> set[str]:
    return set(inflight) & set(files)


def can_run(order: WorkOrder, inflight: Iterable[str]) -> bool:
    """有文件冲突或依赖未满足（依赖列表非空即视为未满足，由调用方先解析）。"""
    if conflicts(inflight, order.scope_files):
        return False
    return not order.dependencies


def parse_worker_output(raw: str, *, required_terms: Sequence[str] = ()) -> WorkerResult:
    """解析子 agent 输出；失败时尽量打捞，但强制标 unverified。"""
    text = raw.strip()
    if not text:
        return WorkerResult("blocked", evidence=(), evidence_status="unverified")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return WorkerResult(
            "partial", output=text[:2000], salvaged=True, evidence_status="unverified"
        )
    if not isinstance(payload, dict):
        return WorkerResult(
            "partial", output=text[:2000], salvaged=True, evidence_status="unverified"
        )
    summary = str(payload.get("summary", "")).strip()
    evidence = tuple(str(item) for item in payload.get("evidence", []) if item)
    missing = [term for term in required_terms if term not in summary]
    if missing:
        return WorkerResult(
            "partial",
            output=summary or text[:2000],
            evidence=evidence,
            salvaged=True,
            evidence_status="unverified",
        )
    return WorkerResult("ok", output=summary, evidence=evidence, evidence_status="verified")
