"""多轮上下文装配（2026-10-20）：唯一纯函数 + 固定裁剪顺序。

分层（预算按权重归一，默认 40/25/15/10/10）：

| 层 | 内容 | 可裁 |
|---|---|---|
| current | 本轮原句 / 取证 / 澄清 / 目标 | **永不**（流程命脉） |
| recent | 最近 2 轮：结论 + 选定方向 + 被否决项 + 待确认 | 是 |
| digest | 更早 6 轮：每轮一句（目标 / 结论 / 未决） | 是 |
| older | 再早的轮次：只保留与本轮目标同符号的 decision | 是 |
| memory | L2 记忆 top-K + 偏好投影 | 是 |

**裁剪顺序固定**：先丢最旧轮的 open → 再丢 rejected/decision → 再压成一句 →
最后才动本轮（本轮永不裁，超出也只记录 `truncated_layers`）。

不读时钟、不读数据库：衰减与检索都由调用方算好再传进来（MUST-06 / 可测性）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

#: 单条摘要的字符上限（三字段合计），避免个别轮次吃掉整层预算。
_SUMMARY_CHAR_LIMIT: Final = 120
_DIGEST_CHAR_LIMIT: Final = 80


def estimate_tokens(text: str) -> int:
    """粗估 token（CJK≈1 字 1 token，其余 4 字符 1 token），与 common/text 同口径。

    这里不 import `common.text`：domain 只声明自身需要的纯函数，避免跨层耦合。
    """
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk + max(0, (len(text) - cjk) // 4)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class TurnSummary:
    """历史轮次的机器摘要（不含原句与绝对路径，MUST-19）。"""

    turn_id: str
    turn_index: int
    target: str = ""
    conclusion: str = ""
    open_items: tuple[str, ...] = ()
    decision: str = ""
    rejected: tuple[str, ...] = ()

    def render(self, *, include_open: bool = True, include_decision: bool = True) -> str:
        parts = [f"第{self.turn_index + 1}轮｜目标 {self.target or '未定位'}｜{self.conclusion}"]
        if include_decision and self.decision:
            parts.append(f"选定 {self.decision}")
        if include_decision and self.rejected:
            parts.append(f"已否决 {'、'.join(self.rejected)}")
        if include_open and self.open_items:
            parts.append(f"待确认 {'；'.join(self.open_items)}")
        return _clip("；".join(parts), _SUMMARY_CHAR_LIMIT)


@dataclass(frozen=True, slots=True)
class TurnInput:
    """本轮输入（永不裁剪的那一层）。"""

    sentence: str = ""
    facts: tuple[str, ...] = ()
    clarifications: dict[str, str] = field(default_factory=dict)
    target: str = ""

    def render(self) -> str:
        lines = [f"本轮需求：{self.sentence}"]
        if self.target:
            lines.append(f"本轮目标：{self.target}")
        if self.facts:
            lines.append("取证件：" + "；".join(self.facts))
        if self.clarifications:
            answers = "；".join(f"{key}={value}" for key, value in self.clarifications.items())
            lines.append(f"已澄清：{answers}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """预算与分层权重（权重和为 1，实现时按比例切分 total）。"""

    total: int = 30000
    weights: tuple[float, ...] = (0.40, 0.25, 0.15, 0.10, 0.10)

    def layer_limits(self) -> tuple[int, ...]:
        return tuple(max(1, int(self.total * weight)) for weight in self.weights)


@dataclass(frozen=True, slots=True)
class ContextPayload:
    """装配结果：历史块 + 记忆块 + 被裁剪的层（供 `state.truncated` 事件与测试断言）。"""

    history_block: str = ""
    memory_block: str = ""
    truncated_layers: tuple[str, ...] = ()

    def render(self) -> str:
        blocks = [block for block in (self.history_block, self.memory_block) if block]
        return "\n\n".join(blocks)


#: 默认预算单例（B008：避免在参数默认值里调用函数）
DEFAULT_BUDGET: Final = ContextBudget()


def _render_recent(items: Sequence[TurnSummary], limit: int, truncated: list[str]) -> str:
    """最近若干轮：先完整，超限再逐步降级（open → decision → 一句结论）。"""
    for include_open, include_decision in ((True, True), (False, True), (False, False)):
        block = "\n".join(
            item.render(include_open=include_open, include_decision=include_decision)
            for item in items
        )
        if estimate_tokens(block) <= limit:
            if (include_open, include_decision) != (True, True):
                truncated.append("recent")
            return block
    truncated.append("recent")
    return "\n".join(
        _clip(item.render(include_open=False, include_decision=False), _DIGEST_CHAR_LIMIT)
        for item in items
    )


def _render_digest(items: Sequence[TurnSummary], limit: int, truncated: list[str]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(
            _clip(item.render(include_open=False, include_decision=False), _DIGEST_CHAR_LIMIT)
        )
        if estimate_tokens("\n".join(lines)) > limit:
            lines.pop()
            truncated.append("digest")
            break
    return "\n".join(lines)


def _render_older(
    items: Sequence[TurnSummary], current_target: str, limit: int, truncated: list[str]
) -> str:
    if not current_target:
        return ""
    lines: list[str] = []
    for item in items:
        if item.target != current_target or not item.decision:
            continue
        lines.append(f"第{item.turn_index + 1}轮｜{item.decision}｜{_clip(item.conclusion, 40)}")
        if estimate_tokens("\n".join(lines)) > limit:
            lines.pop()
            truncated.append("older")
            break
    return "\n".join(lines)


def _render_memory(notes: Sequence[str], limit: int, truncated: list[str]) -> str:
    lines = [f"- {note}" for note in notes if note.strip()]
    block = "\n".join(lines)
    if estimate_tokens(block) <= limit:
        return block
    truncated.append("memory")
    kept: list[str] = []
    for line in lines:
        kept.append(line)
        if estimate_tokens("\n".join(kept)) > limit:
            kept.pop()
            break
    return "\n".join(kept)


def build_context(
    turns: Sequence[TurnSummary],
    current: TurnInput,
    *,
    notes: Sequence[str] = (),
    budget: ContextBudget = DEFAULT_BUDGET,
) -> ContextPayload:
    """按层装配历史上下文（`turns` 为升序，最后一条是最近一轮）。

    返回的 `history_block` 可直接拼进生成 prompt；`memory_block` 单独一块，
    便于调用方在超预算时优先保留记忆或反之。
    """
    _current_limit, recent_limit, digest_limit, older_limit, memory_limit = budget.layer_limits()
    truncated: list[str] = []

    # current 层永不裁：超出只记录，不截断
    if estimate_tokens(current.render()) > budget.layer_limits()[0]:
        truncated.append("current")

    recent_turns = list(turns[-2:])
    older_turns = list(turns[:-2])
    digest_turns = older_turns[-6:]
    very_old_turns = older_turns[:-6]

    blocks = [
        _render_recent(recent_turns, recent_limit, truncated),
        _render_digest(digest_turns, digest_limit, truncated),
        _render_older(very_old_turns, current.target, older_limit, truncated),
    ]
    history_block = "\n".join(block for block in blocks if block)
    memory_block = _render_memory(notes, memory_limit, truncated)
    return ContextPayload(
        history_block=history_block,
        memory_block=memory_block,
        truncated_layers=tuple(dict.fromkeys(truncated)),
    )


def summary_from_turn(data: dict[str, Any]) -> dict[str, Any]:
    """从会话数据规则提取机器摘要（**不调 LLM**，省钱且稳定）。

    只留三字段 + 决策/否决：`target / conclusion / open / decision / rejected`。
    不含原句与绝对路径（MUST-19）——`target` 只取符号名。
    """
    target_data = data.get("target")
    target = str(target_data.get("name", "")) if isinstance(target_data, dict) else ""

    variants = [item for item in data.get("variants", []) if isinstance(item, dict)]
    ranking = data.get("ranking")
    decision = ""
    if isinstance(ranking, dict) and ranking.get("variant"):
        decision = str(ranking["variant"])
    elif variants:
        decision = str(variants[0].get("level", ""))

    chosen = next((item for item in variants if str(item.get("level")) == decision), None)
    if chosen is None and variants:
        chosen = variants[0]
    conclusion = str(chosen.get("title", "")) if chosen is not None else ""
    if not conclusion:
        conclusion = "已完成" if data.get("variants") else "待补充信息"

    rejected = [
        f"{item.get('level')} {item.get('title')}"
        for item in variants
        if str(item.get("level")) != decision and item.get("title")
    ]

    unknowns = [item for item in data.get("unknowns", []) if isinstance(item, dict)]
    open_items = [str(item.get("ask", "")) for item in unknowns if item.get("ask")][:3]

    return {
        "target": target,
        "conclusion": _clip(conclusion, _SUMMARY_CHAR_LIMIT),
        "facts_complete": bool(data.get("facts_complete", False)),
        "open": open_items,
        "decision": decision,
        "rejected": rejected[:2],
    }
