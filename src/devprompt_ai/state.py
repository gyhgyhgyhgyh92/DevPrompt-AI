"""F-002 优化流程状态机（唯一实现，MUST-07）；乐观锁串行化（MUST-11）。"""

from __future__ import annotations

import uuid
from enum import Enum

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import FlowSession, SessionStore


class FlowState(str, Enum):
    INIT = "INIT"
    RETRIEVING = "RETRIEVING"
    PROBING = "PROBING"
    ASKING = "ASKING"
    CONFIRMING = "CONFIRMING"
    GENERATING = "GENERATING"
    RANKING = "RANKING"
    DONE = "DONE"
    ABORTED = "ABORTED"


# GENERATING→RANKING 为阶段五推荐接入预留；阶段四单套走 GENERATING→DONE。
# RETRIEVING→ASKING：F-102 候选 <3 条（manual_required）直达反问。
TRANSITIONS: dict[FlowState, frozenset[FlowState]] = {
    FlowState.INIT: frozenset({FlowState.RETRIEVING, FlowState.ABORTED}),
    FlowState.RETRIEVING: frozenset({FlowState.PROBING, FlowState.ASKING, FlowState.ABORTED}),
    FlowState.PROBING: frozenset({FlowState.ASKING, FlowState.GENERATING, FlowState.ABORTED}),
    FlowState.ASKING: frozenset({FlowState.CONFIRMING, FlowState.GENERATING, FlowState.ABORTED}),
    FlowState.CONFIRMING: frozenset({FlowState.ASKING, FlowState.GENERATING, FlowState.ABORTED}),
    FlowState.GENERATING: frozenset({FlowState.RANKING, FlowState.DONE, FlowState.ABORTED}),
    FlowState.RANKING: frozenset({FlowState.DONE, FlowState.ABORTED}),
    FlowState.DONE: frozenset(),
    FlowState.ABORTED: frozenset(),
}


def new_session_id() -> str:
    return uuid.uuid4().hex


def validate_transition(current: FlowState, target: FlowState) -> None:
    if target not in TRANSITIONS[current]:
        raise StateError(
            f"非法状态转移 {current.value} -> {target.value}",
            code=6001,
            context={"current": current.value, "target": target.value},
        )


async def transition(session: FlowSession, target: FlowState, store: SessionStore) -> None:
    """校验转移并 CAS 持久化；版本冲突抛 StateError(6001)，非法转移不落盘。"""
    validate_transition(FlowState(session.state), target)
    session.state = target.value
    if not await store.save(session):
        raise StateError(
            "会话版本冲突，拒绝写入（乐观锁）",
            code=6001,
            context={"session_id": session.session_id},
        )


async def load_or_create(
    store: SessionStore, user_id: str, session_id: str | None = None
) -> FlowSession:
    if session_id is not None:
        session = await store.load(session_id)
        if session is None:
            raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
        return session
    session = FlowSession(session_id=new_session_id(), user_id=user_id, state=FlowState.INIT.value)
    await store.create(session)
    return session
