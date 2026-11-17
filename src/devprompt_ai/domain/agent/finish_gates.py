"""natural-finish 六道闸（A2）：模型说「做完了」不等于真的做完。

顺序固定，任一闸拦截即返回；只有六道全过才允许自然收尾。
纯函数：输入是已收集好的事实（文本、steer、goal、义务），不读会话、不调 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FinishGate(str, Enum):
    THINKING_RETRY = "thinking-retry"
    STEER = "steer"
    GOAL = "goal"
    NO_ANSWER = "no-answer"
    ACTION_INTENT = "action-intent"
    OBLIGATION = "obligation"


@dataclass(frozen=True, slots=True)
class GateInput:
    has_text: bool
    text_looks_like_thinking: bool = False
    retry_budget_left: bool = True
    pending_steer: str = ""
    pending_goal: str = ""
    states_future_action: bool = False
    pending_obligation: str = ""


@dataclass(frozen=True, slots=True)
class FinishDecision:
    allowed: bool
    blocked_by: FinishGate | None = None
    detail: str = ""


def evaluate_finish(data: GateInput) -> FinishDecision:
    """返回是否允许自然收尾；被拦时给出闸名与原因。"""
    if data.text_looks_like_thinking and data.retry_budget_left:
        return FinishDecision(False, FinishGate.THINKING_RETRY, "文本仍是思考而非结论")

    if data.pending_steer.strip():
        return FinishDecision(False, FinishGate.STEER, data.pending_steer.strip())

    if data.pending_goal.strip():
        return FinishDecision(False, FinishGate.GOAL, data.pending_goal.strip())

    # 空回答不算完成：即便前面都过，没有正文也不能收尾。
    if not data.has_text:
        return FinishDecision(False, FinishGate.NO_ANSWER, "没有可交付的正文")

    if data.states_future_action:
        return FinishDecision(False, FinishGate.ACTION_INTENT, "声称将要做某事但没有实际动作")

    if data.pending_obligation.strip():
        return FinishDecision(False, FinishGate.OBLIGATION, data.pending_obligation.strip())

    return FinishDecision(True)
