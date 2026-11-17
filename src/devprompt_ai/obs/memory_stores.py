"""Replay 用的内存会话/轮次存储（不写真实 DB）。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.models import FlowSession, SessionSummary, TurnRecord
from devprompt_ai.memory.turn_store import TurnConflictError


class MemorySessionStore:
    def __init__(self) -> None:
        self.items: dict[str, FlowSession] = {}

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        summaries = [
            SessionSummary(
                session_id=item.session_id,
                state=item.state,
                project=str(item.data.get("project_root", ""))
                .replace("\\", "/")
                .rsplit("/", 1)[-1],
                updated_at="",
                title=str(item.data.get("sentence", ""))[:40],
                project_root=str(item.data.get("project_root", "")),
            )
            for item in self.items.values()
            if item.user_id == user_id
        ]
        return summaries[offset : offset + limit]

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        removed = [
            key
            for key, item in self.items.items()
            if item.user_id == user_id and item.data.get("project_root") == project_root
        ]
        for key in removed:
            self.items.pop(key, None)
        return len(removed)


class MemoryTurnStore:
    def __init__(self) -> None:
        self.items: dict[str, TurnRecord] = {}

    async def append(self, turn: TurnRecord) -> None:
        if any(
            item.session_id == turn.session_id and item.turn_index == turn.turn_index
            for item in self.items.values()
        ):
            raise TurnConflictError(f"turn 已存在：{turn.session_id} index={turn.turn_index}")
        self.items[turn.turn_id] = turn

    async def finish(
        self,
        turn_id: str,
        *,
        state: str,
        facts: list[dict[str, Any]],
        clarifications: dict[str, str],
        output: list[dict[str, Any]],
        summary: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        turn = self.items.get(turn_id)
        if turn is None:
            return
        turn.state = state
        turn.facts = facts
        turn.clarifications = clarifications
        turn.output = output
        turn.summary = summary
        turn.usage = usage

    async def list_for_session(
        self, session_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[TurnRecord]:
        rows = sorted(
            (item for item in self.items.values() if item.session_id == session_id),
            key=lambda item: item.turn_index,
        )
        if limit is None:
            return rows
        return rows[max(0, len(rows) - offset - limit) : len(rows) - offset]

    async def load(self, turn_id: str) -> TurnRecord | None:
        return self.items.get(turn_id)

    async def delete_after(self, session_id: str, turn_index: int) -> int:
        removed = [
            key
            for key, item in self.items.items()
            if item.session_id == session_id and item.turn_index > turn_index
        ]
        for key in removed:
            self.items.pop(key, None)
        return len(removed)
