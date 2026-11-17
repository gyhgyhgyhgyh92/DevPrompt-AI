"""Trace 标准契约（三模块唯一共享的数据模型，纯数据零 I/O）。

设计对齐 DeerFlow 的节点化执行思路：每个节点是一次可寻址的调用，父子关系构成调用链，
录制结果按 ``call_key`` 寻址，供 Replay 模块确定性重放。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Final

from devprompt_ai.domain.obs.contract.version import TRACE_SCHEMA_VERSION

#: 密钥类字段名（大小写不敏感，包含匹配）：写入 Trace 前必须掩码（MUST-19 例外边界）。
_SECRET_KEY_PARTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "password",
)


class TraceKind(str, Enum):
    TURN_START = "turn.start"
    TURN_END = "turn.end"
    ACTION_START = "action.start"
    ACTION_END = "action.end"
    DECISION = "decision.request"
    DECISION_RESULT = "decision.response"
    LLM = "llm.request"
    LLM_RESULT = "llm.response"
    TOOL = "tool.call"
    TOOL_RESULT = "tool.result"
    FILE = "file.read"
    SYMBOLS = "symbols.scan"
    GATE = "gate.evaluate"
    SENSORIUM = "sensorium.snapshot"


class TraceStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """一条完整 Trace 事件；input/output 为全量明文（密钥字段已掩码）。"""

    event_id: str
    trace_id: str
    session_id: str
    turn_id: str
    turn_index: int
    run_id: str
    seq: int
    parent_id: str
    kind: str
    name: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_row(self) -> tuple[object, ...]:
        return (
            self.trace_id,
            self.seq,
            self.event_id,
            self.session_id,
            self.turn_id,
            self.turn_index,
            self.run_id,
            self.parent_id,
            self.kind,
            self.name,
            self.status,
            self.started_at,
            self.ended_at,
            self.duration_ms,
            canonical_json(self.input),
            canonical_json(self.output),
            canonical_json(self.error),
            canonical_json(self.attributes),
            self.schema_version,
        )

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TraceEvent:
        (
            trace_id,
            seq,
            event_id,
            session_id,
            turn_id,
            turn_index,
            run_id,
            parent_id,
            kind,
            name,
            status,
            started_at,
            ended_at,
            duration_ms,
            input_json,
            output_json,
            error_json,
            attributes_json,
            schema_version,
        ) = row
        return cls(
            event_id=str(event_id),
            trace_id=str(trace_id),
            session_id=str(session_id),
            turn_id=str(turn_id),
            turn_index=int(turn_index),
            run_id=str(run_id or ""),
            seq=int(seq),
            parent_id=str(parent_id or ""),
            kind=str(kind),
            name=str(name),
            status=str(status),
            started_at=str(started_at),
            ended_at=str(ended_at or ""),
            duration_ms=int(duration_ms or 0),
            input=_loads(input_json),
            output=_loads(output_json),
            error=_loads(error_json),
            attributes=_loads(attributes_json),
            schema_version=int(schema_version),
        )

    def to_payload(self, *, full: bool = False) -> dict[str, Any]:
        """JSON 友好结构；``full=False`` 时 input/output 只给 preview。"""
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "run_id": self.run_id,
            "seq": self.seq,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "input": self.input if full else preview(self.input),
            "output": self.output if full else preview(self.output),
            "error": self.error,
            "attributes": self.attributes,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """一次 turn 的 Trace 概览（列表页用，不含事件正文）。"""

    trace_id: str
    session_id: str
    turn_id: str
    turn_index: int
    started_at: str
    ended_at: str
    event_count: int
    failed_count: int
    input_hash: str
    status: str
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "event_count": self.event_count,
            "failed_count": self.failed_count,
            "input_hash": self.input_hash,
            "status": self.status,
            "schema_version": self.schema_version,
        }


def _loads(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def canonical_json(value: object) -> str:
    """稳定 JSON：键排序、紧凑分隔符；用于 call_key 与节点比较。"""
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def hash_key(*parts: object) -> str:
    return hashlib.sha256(
        "|".join(canonical_json(part) for part in parts).encode("utf-8")
    ).hexdigest()


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def normalize_decision_args(args: dict[str, Any]) -> dict[str, Any]:
    """决策入参归一化：剔除运行期抖动后复算 ``call_key``（录制与回放必须同构）。

    关键点是 ``steps`` 里的 ``duration_ms``——它每次执行都不同，若参与哈希，
    回放永远命中不了录制（2026-11-12 集成测试实测）。这里只保留影响决策语义的
    字段；``facts`` 等 dataclass 统一展开为字典，避免依赖 repr 的稳定性。
    """
    stable = dict(args)
    raw_steps = stable.get("steps")
    if raw_steps is not None:
        stable["steps"] = [
            {
                "index": int(getattr(step, "index", 0)),
                "action": _enum_value(getattr(step, "action", "")),
                "outcome": _enum_value(getattr(step, "outcome", "")),
                "facts_passed": int(getattr(step, "facts_passed", 0)),
                "decided_by_evidence": bool(getattr(step, "decided_by_evidence", True)),
                "note": str(getattr(step, "note", "")),
            }
            for step in raw_steps
        ]
    raw_facts = stable.get("facts")
    if raw_facts is not None:
        stable["facts"] = [
            asdict(item) if is_dataclass(item) and not isinstance(item, type) else item
            for item in raw_facts
        ]
    return stable


def to_plain(value: object) -> Any:
    """递归转 JSON 可序列化结构（dataclass / Pydantic / Enum / 容器）。

    ``dataclasses.asdict`` 不认 Pydantic 模型（如 ``VariantDraft``），直接
    ``json.dumps`` 会在落库时抛 TypeError——录 Trace 与回放结果都必须先过这里。
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return to_plain(dump())
    return value


def preview(value: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    """列表页预览：只保留前 ``limit`` 字符的 JSON 文本，避免大 payload。"""
    text = canonical_json(value)
    return {"preview": text[:limit], "truncated": len(text) > limit, "chars": len(text)}


def mask_secrets(value: object) -> Any:
    """递归掩码密钥字段；其余内容按用户批准保留明文。

    ``images`` 键（2026-11-14 多模态）：base64 参考图不入 trace，只留数量与体积标记。
    """
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SECRET_KEY_PARTS):
                masked[str(key)] = "***"
            elif lowered == "images" and isinstance(item, (list, tuple)):
                masked[str(key)] = _mask_images(item)
            else:
                masked[str(key)] = mask_secrets(item)
        return masked
    if isinstance(value, (list, tuple)):
        return [mask_secrets(item) for item in value]
    return value


def _mask_images(items: list[Any] | tuple[Any, ...]) -> list[str]:
    """图像列表 → 占位符（保留张数与粗略体积，便于回放时判断 payload 规模）。"""
    return [f"[image{index + 1}: ~{len(str(raw)) // 1024}KB]" for index, raw in enumerate(items)]
