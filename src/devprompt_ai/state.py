"""F-002 优化流程状态机（唯一实现，MUST-07）；乐观锁串行化（MUST-11）。"""

from __future__ import annotations

import uuid
from enum import Enum

from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.models import FlowSession, SessionStore


class FlowState(str, Enum):
    INIT = "INIT"
    #: 决策态：每完成一个动作回到这里，由 DecisionPort.next_action 决定下一步。
    AGENTIC = "AGENTIC"
    RETRIEVING = "RETRIEVING"
    PROBING = "PROBING"
    ASKING = "ASKING"
    CONFIRMING = "CONFIRMING"
    GENERATING = "GENERATING"
    DONE = "DONE"
    ABORTED = "ABORTED"


# 星型拓扑（2026-11-04）：AGENTIC 是唯一枢纽，执行态完成后一律回到它，
# 再由它决定下一个动作。保留一条既有快速路径，它不经过决策态：
#   GENERATING→DONE（2026-11-11 单套交付）。
# DONE / ABORTED 出边为空：一轮结束由 start_turn 重置容器，不经转移边。
TRANSITIONS: dict[FlowState, frozenset[FlowState]] = {
    FlowState.INIT: frozenset({FlowState.AGENTIC, FlowState.ABORTED}),
    FlowState.AGENTIC: frozenset(
        {
            FlowState.RETRIEVING,
            FlowState.PROBING,
            FlowState.ASKING,
            FlowState.CONFIRMING,
            FlowState.GENERATING,
            FlowState.DONE,
            FlowState.ABORTED,
        }
    ),
    FlowState.RETRIEVING: frozenset({FlowState.AGENTIC, FlowState.ABORTED}),
    FlowState.PROBING: frozenset({FlowState.AGENTIC, FlowState.ABORTED}),
    FlowState.ASKING: frozenset({FlowState.AGENTIC, FlowState.ABORTED}),
    FlowState.CONFIRMING: frozenset({FlowState.AGENTIC, FlowState.ABORTED}),
    FlowState.GENERATING: frozenset(
        {
            FlowState.AGENTIC,
            FlowState.DONE,
            FlowState.ABORTED,
        }
    ),
    FlowState.DONE: frozenset(),
    FlowState.ABORTED: frozenset(),
}

#: 活跃态：进程在这些状态下崩溃会留下需要启动自愈的孤儿 turn。
#: ASKING / CONFIRMING 是「等用户」而不是「执行中」，不计入崩溃孤儿。
ACTIVE_STATES: frozenset[FlowState] = frozenset(
    {
        FlowState.INIT,
        FlowState.AGENTIC,
        FlowState.RETRIEVING,
        FlowState.PROBING,
        FlowState.GENERATING,
    }
)


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


async def hop(session: FlowSession, target: FlowState, store: SessionStore) -> None:
    """经 AGENTIC 中转进入执行态（星型拓扑下的唯一合法路径）。

    已在 AGENTIC 时直接转；目标就是 AGENTIC 时只做回巢，避免自环。
    两次 CAS 之间失败会让 session 停在 AGENTIC——那是合法检查点，不是半成品。
    """
    if FlowState(session.state) is not FlowState.AGENTIC:
        await transition(session, FlowState.AGENTIC, store)
    if target is FlowState.AGENTIC:
        return
    await transition(session, target, store)


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


async def start_turn(
    store: SessionStore,
    user_id: str,
    session_id: str | None,
    *,
    create_missing: bool = False,
) -> FlowSession:
    """开始新一轮（2026-10-20 多轮）：无 id 新建会话；有 id 则复用容器并重置到 INIT。

    ``create_missing``：/runs 的前端会话由 ``crypto.randomUUID()`` 预先生成，
    执行侧需要按该 id 建容器（2026-11-14 D-04）。默认 False——旧入口传未知 id
    仍按 6003 拒绝，契约不变。

    **为什么不经 transition**：状态机作用域属于 turn（MUST-07 语义调整，非新增态）。
    DONE / ABORTED 是**上一轮 turn** 的终态，session 只是容器——容器重开一轮不需要
    状态转移边，否则就得给 DONE 加出边，连带 SSE 关闭条件、`resume` 的已结束判定、
    权限白名单、前端 done 视图四处假设同时失效。

    星型拓扑（2026-11-04）下 AGENTIC 属活跃态：撞上它说明上一轮仍在决策/执行，
    与撞上其他活跃态一样拒绝重开；进程崩溃留下的 AGENTIC 由启动自愈置为 ABORTED。
    """
    if session_id is None:
        return await load_or_create(store, user_id)
    session = await store.load(session_id)
    if session is None:
        if not create_missing:
            raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
        session = FlowSession(
            session_id=session_id,
            user_id=user_id,
            state=FlowState.DONE.value,
            data={},
        )
        await store.create(session)
    elif session.user_id != user_id:
        raise StateError("流程 ID 不存在", code=6003, context={"session_id": session_id})
    current = FlowState(session.state)
    if current not in {FlowState.DONE, FlowState.ABORTED}:
        raise StateError(
            "当前轮次尚未结束，不能开启新一轮",
            code=6001,
            context={"session_id": session_id, "state": current.value},
        )
    session.state = FlowState.INIT.value
    if not await store.save(session):
        raise StateError(
            "会话版本冲突，拒绝写入（乐观锁）",
            code=6001,
            context={"session_id": session_id},
        )
    return session
