"""录制结果回放：按 ``call_key`` 取原始 Trace 的输入/输出（纯逻辑）。"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceKind


@dataclass(frozen=True, slots=True)
class PlaybackRecord:
    event_id: str
    seq: int
    kind: str
    name: str
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass
class Playback:
    """同 key 多次调用按录制顺序消费；缺失 key 记录在 ``missing``。"""

    _queues: dict[tuple[str, str], deque[PlaybackRecord]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    _all: dict[str, PlaybackRecord] = field(default_factory=dict)

    @classmethod
    def from_events(cls, events: Sequence[TraceEvent]) -> Playback:
        playback = cls()
        accepted = {
            TraceKind.TOOL_RESULT.value,
            TraceKind.LLM_RESULT.value,
            TraceKind.DECISION_RESULT.value,
            TraceKind.FILE.value,
            TraceKind.SYMBOLS.value,
        }
        for event in sorted(events, key=lambda item: item.seq):
            if event.kind not in accepted:
                continue
            key = str(event.attributes.get("call_key", ""))
            if key == "":
                continue
            record = PlaybackRecord(
                event_id=event.event_id,
                seq=event.seq,
                kind=event.kind,
                name=event.name,
                input=event.input,
                output=event.output,
            )
            playback._queues.setdefault((event.kind, key), deque()).append(record)
            playback._all[event.event_id] = record
        return playback

    def take(self, kind: str, call_key: str) -> PlaybackRecord | None:
        queue = self._queues.get((kind, call_key))
        if not queue:
            self.missing.append(f"{kind}:{call_key}")
            return None
        return queue.popleft()

    def records(self) -> list[PlaybackRecord]:
        return list(self._all.values())
