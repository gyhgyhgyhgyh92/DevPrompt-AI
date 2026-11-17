"""任务契约（B13–B14）：目标/范围/约束/验收的权威载体。

与 `domain/agent/anchor.py` 的关系：anchor 是轻量锚点（四字段），契约多出
``status`` / ``is_actionable`` / 三态分类。两者共用同一套抽取正则，避免两处漂移。

压缩后契约会从投影里消失，因此必须能在消息**尾部**重新注入（`render_tail_anchor`），
并显式声明「与摘要冲突时以本块为准」——这是对抗摘要漂移的 ground truth。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from devprompt_ai.domain.agent.anchor import (
    TurnAnchor,
    _extract_constraints,
    _extract_paths,
    _normalize_objective,
)

DEFAULT_CRITERIA: Final[tuple[str, ...]] = (
    "产出的提示词可直接复制给编码 Agent 执行",
    "正文中的路径与行号必须来自本次取证，不得编造",
)

#: 续写指令：有活跃契约时视为 follow-up，而不是新任务。
_CONTINUATION: Final[tuple[str, ...]] = (
    "继续",
    "接着",
    "下一个",
    "再改",
    "还有",
    "然后",
    "continue",
    "next",
)
_GREETINGS: Final[tuple[str, ...]] = ("你好", "hi", "hello", "谢谢", "在吗")
#: 可执行目标的最小权重：短中文（CJK 权重 2）也要能过线。
_MIN_ACTIONABLE_WEIGHT: Final[int] = 6


class TurnMode(str, Enum):
    CHAT = "chat"
    FOLLOW_UP = "follow-up"
    TASK = "task"


class ContractStatus(str, Enum):
    EXPLORING = "exploring"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    BLOCKED = "blocked"
    READY = "ready-to-deliver"


@dataclass(frozen=True, slots=True)
class TaskContract:
    objective: str
    scope_paths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = DEFAULT_CRITERIA
    status: ContractStatus = ContractStatus.EXPLORING
    is_actionable: bool = True
    created_at_turn: int = 0
    updated_at_turn: int = 0


def cjk_weight(text: str) -> int:
    """CJK 字符按 2 计、其余按 1 计——中文短句不能被当成闲聊。"""
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk * 2 + (len(text) - cjk)


def _is_actionable(sentence: str) -> bool:
    lowered = sentence.strip().lower()
    if not lowered or any(lowered.startswith(greeting) for greeting in _GREETINGS):
        return False
    return cjk_weight(sentence) >= _MIN_ACTIONABLE_WEIGHT


def classify_turn_mode(sentence: str, *, has_contract: bool) -> TurnMode:
    """三态分流：闲聊 / 续写 / 新任务。"""
    text = sentence.strip()
    if not text:
        return TurnMode.CHAT
    lowered = text.lower()
    if has_contract and any(word in lowered for word in _CONTINUATION):
        return TurnMode.FOLLOW_UP
    if not has_contract and not _is_actionable(text):
        return TurnMode.CHAT
    return TurnMode.TASK


def extract_contract(sentence: str, turn_index: int) -> TaskContract:
    anchor = TurnAnchor(
        objective=_normalize_objective(sentence),
        scope_paths=_extract_paths(sentence),
        constraints=_extract_constraints(sentence),
    )
    return TaskContract(
        objective=anchor.objective,
        scope_paths=anchor.scope_paths,
        constraints=anchor.constraints,
        is_actionable=_is_actionable(sentence),
        created_at_turn=turn_index,
        updated_at_turn=turn_index,
    )


def merge_followup(contract: TaskContract, sentence: str, *, turn_index: int) -> TaskContract:
    """只补范围与约束，**不重写 objective**（防止后轮模糊表述覆盖明确目标）。"""
    scope = tuple(dict.fromkeys((*contract.scope_paths, *_extract_paths(sentence))))[:6]
    constraints = tuple(dict.fromkeys((*contract.constraints, *_extract_constraints(sentence))))[:4]
    if scope == contract.scope_paths and constraints == contract.constraints:
        return contract
    return replace(
        contract,
        scope_paths=scope,
        constraints=constraints,
        updated_at_turn=turn_index,
    )


def with_status(contract: TaskContract, status: ContractStatus) -> TaskContract:
    return replace(contract, status=status)


def render_contract_projection(contract: TaskContract) -> str:
    """常规轮投影：随上下文增量走，只在状态迁移时变字节。"""
    lines = [f"【当前目标】{contract.objective}", f"【状态】{contract.status.value}"]
    if contract.scope_paths:
        lines.append("【范围】" + "、".join(contract.scope_paths))
    if contract.constraints:
        lines.append("【约束】" + "；".join(contract.constraints))
    return "\n".join(lines)


def render_tail_anchor(
    contract: TaskContract,
    *,
    completed: tuple[str, ...] = (),
    remaining: tuple[str, ...] = (),
) -> str:
    """压缩后注入消息尾部的权威块；永不进冻结前缀（缓存安全）。"""
    lines = [
        '<task-anchor authoritative="true">',
        "若上方摘要与本块冲突，以本块为准。",
        f"目标：{contract.objective}",
        f"状态：{contract.status.value}",
    ]
    if contract.scope_paths:
        lines.append("范围：" + "、".join(contract.scope_paths))
    if contract.constraints:
        lines.append("约束：" + "；".join(contract.constraints))
    lines.append("成功标准：" + "；".join(contract.success_criteria))
    if completed:
        lines.append("已完成：" + "；".join(completed))
    if remaining:
        lines.append("待完成：" + "；".join(remaining))
    lines.append("</task-anchor>")
    return "\n".join(lines)
