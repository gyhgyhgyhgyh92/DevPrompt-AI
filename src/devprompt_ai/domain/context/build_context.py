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

from devprompt_ai.domain.context.budget import fit_blocks
from devprompt_ai.domain.context.compact_economics import Billing, reclaim_floor
from devprompt_ai.domain.context.compact_policy import CacheKind
from devprompt_ai.domain.context.compactor import confirm_reclaim, plan_compaction

#: 单条摘要的字符上限（三字段合计），避免个别轮次吃掉整层预算。
_SUMMARY_CHAR_LIMIT: Final = 120
_DIGEST_CHAR_LIMIT: Final = 80
#: 纯回答轮的摘要上限（2026-11-05）：比普通轮长，否则「接着刚才说的」接不上。
#: 普通轮仍用 120——回答轮的正文本身就是这轮的全部产出。
_REPLY_SUMMARY_LIMIT: Final = 260
#: 动作序列在摘要里的条数上限（2026-11-05）：够回看「做过哪几步」，又不撑大摘要。
_SUMMARY_STEPS_LIMIT: Final = 24
#: 六维快照可落库的键（白名单）：只允许这 7 个数值维度，防止任意键混入 summary_json。
_SENSORIUM_KEYS: Final = (
    "momentum",
    "pressure",
    "coverage",
    "complexity",
    "familiarity",
    "stability",
    "score",
)


def estimate_tokens(text: str) -> int:
    """统一口径（2026-11-19）：委托 `tokens.estimate_tokens`，消除 CJK 1 与 1.2 两套估算。"""
    from devprompt_ai.domain.context.tokens import estimate_tokens as _estimate

    return _estimate(text)


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
    #: 纯回答轮的正文摘要（2026-11-05）：本轮没有方案，结论会退化成「待补充信息」
    reply: str = ""

    def render(self, *, include_open: bool = True, include_decision: bool = True) -> str:
        parts = [f"第{self.turn_index + 1}轮｜目标 {self.target or '未定位'}｜{self.conclusion}"]
        if self.reply:
            parts.append(f"回答 {self.reply}")
        if include_decision and self.decision:
            parts.append(f"选定 {self.decision}")
        if include_decision and self.rejected:
            parts.append(f"已否决 {'、'.join(self.rejected)}")
        if include_open and self.open_items:
            parts.append(f"待确认 {'；'.join(self.open_items)}")
        # 回答轮给更长的上限：正文本身就是这一轮的全部产出，截到 120 会答不上追问
        limit = _REPLY_SUMMARY_LIMIT if self.reply else _SUMMARY_CHAR_LIMIT
        return _clip("；".join(parts), limit)


@dataclass(frozen=True, slots=True)
class TurnInput:
    """本轮输入（永不裁剪的那一层）。"""

    sentence: str = ""
    facts: tuple[str, ...] = ()
    clarifications: dict[str, str] = field(default_factory=dict)
    target: str = ""
    #: 本轮目标锚点渲染块（2026-11-05）。放首行：历史被压成 80 字摘要后，
    #: 目标是唯一不能跟着漂的东西。缺省空串保证旧调用方零改动。
    anchor: str = ""

    def render(self) -> str:
        lines = [self.anchor] if self.anchor else []
        lines.append(f"本轮需求：{self.sentence}")
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


def compose_history(history: str, *, ledger: str = "", anchor: str = "") -> str:
    """固定顺序拼接：历史 → 认知账本 → 权威锚点；空块跳过。"""
    parts = [part for part in (history, ledger.strip(), anchor.strip()) if part]
    return "\n\n".join(parts)


def build_context(
    turns: Sequence[TurnSummary],
    current: TurnInput,
    *,
    notes: Sequence[str] = (),
    budget: ContextBudget = DEFAULT_BUDGET,
    context_window: int = 0,
    estimated_tokens: int = 0,
    cache_kind: CacheKind = CacheKind.AUTOMATIC,
    tail_anchor: str = "",
    ledger_block: str = "",
    delta_block: str = "",
) -> ContextPayload:
    """按层装配历史上下文（`turns` 为升序，最后一条是最近一轮）。

    传入 `context_window` 与 `estimated_tokens` 时启用压缩：按计划缩放
    recent/digest/older/memory 四层预算；**current 层永不压**。

    返回的 `history_block` 可直接拼进生成 prompt；`memory_block` 单独一块，
    便于调用方在超预算时优先保留记忆或反之。
    """
    limits = budget.layer_limits()
    truncated: list[str] = []
    if context_window > 0 and estimated_tokens > 0:
        plan = plan_compaction(
            estimated_tokens=estimated_tokens,
            window=context_window,
            cache_kind=cache_kind,
        )
        if plan.should_compact:
            ratio = plan.budget_ratio
            scaled = (
                limits[0],
                int(limits[1] * ratio),
                int(limits[2] * ratio),
                int(limits[3] * ratio),
                int(limits[4] * ratio),
            )
            # 经济性否决门（2026-11-19）：回收不足时回滚缩放，避免白付 prefill。
            floor = reclaim_floor(
                billing=Billing.SUBSCRIPTION, cache_kind=cache_kind, window=context_window
            )
            verdict = confirm_reclaim(
                before_tokens=estimated_tokens,
                after_tokens=int(estimated_tokens * ratio),
                floor=floor,
                force=plan.force,
            )
            if verdict.worthwhile:
                limits = scaled
                truncated.append(f"compacted:{plan.action.value}")
            else:
                truncated.append(f"reclaim_rejected:{verdict.reason}")
    current_limit, recent_limit, digest_limit, older_limit, memory_limit = limits

    # current 层永不裁：超出只记录，不截断
    if estimate_tokens(current.render()) > current_limit:
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
    body = "\n".join(block for block in blocks if block)
    # B1–B4：增量附录（<context-update>）紧跟历史，仍在账本与权威块之前
    if delta_block.strip():
        body = f"{body}\n\n{delta_block.strip()}" if body else delta_block.strip()
    # B15：认知账本在历史之后；B13/B14：权威块永远最后（不碰冻结前缀，缓存安全）
    history_block = compose_history(body, ledger=ledger_block, anchor=tail_anchor)
    # B17：记忆块按块级配额硬裁，防止单块吃光整窗
    memory_block = fit_blocks(
        {"project_memory": _render_memory(notes, memory_limit, truncated)}
    ).get("project_memory", "")
    return ContextPayload(
        history_block=history_block,
        memory_block=memory_block,
        truncated_layers=tuple(dict.fromkeys(truncated)),
    )


def summary_from_turn(data: dict[str, Any]) -> dict[str, Any]:
    """从会话数据规则提取机器摘要（**不调 LLM**，省钱且稳定）。

    只留三字段 + 决策/否决：`target / conclusion / open / decision / rejected`。
    不含原句与绝对路径（MUST-19）——`target` 只取符号名。

    另附三块**观测数据**（2026-11-05）：`level / claims / sensorium`，全为数值，
    供离线统计声明率与六维分布用；上下文装配只按字段取用既有键，不进 prompt。
    """
    target_data = data.get("target")
    target = str(target_data.get("name", "")) if isinstance(target_data, dict) else ""

    variants = [item for item in data.get("variants", []) if isinstance(item, dict)]
    # 仅用于 2026-11-11 之前的历史轮次回放：新轮次为单套输出，不再写入 ranking。
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

    reply = str(data.get("reply_text", "")).strip()
    # 动作序列（2026-11-05 形态层）：历史轮可回看「这一步在做什么」。
    # 随摘要一起落进 summary_json——**不新增表列**（零 DDL 迁移、零旧库兼容风险）。
    steps = [item for item in data.get("agent_steps", []) if isinstance(item, dict)]

    # 六维快照（2026-11-05）：纯数值，白名单取键，不含原句与绝对路径（MUST-19）。
    sensorium_raw = data.get("sensorium")
    sensorium: dict[str, float] = {}
    if isinstance(sensorium_raw, dict):
        for key in _SENSORIUM_KEYS:
            value = sensorium_raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sensorium[key] = float(value)

    # 断言对账（2026-11-05）：只取计数与布尔标记，uncovered 文本不进库。
    claim_raw = data.get("claim_report")
    claims: dict[str, Any] = {}
    if isinstance(claim_raw, dict):
        claims = {
            "total": int(claim_raw.get("total", 0)),
            "covered": int(claim_raw.get("covered", 0)),
            "undeclared": bool(claim_raw.get("undeclared", False)),
        }

    return {
        "target": target,
        "conclusion": _clip(conclusion, _SUMMARY_CHAR_LIMIT),
        "facts_complete": bool(data.get("facts_complete", False)),
        "open": open_items,
        "decision": decision,
        "rejected": rejected[:2],
        # 纯回答轮（2026-11-05）：本轮没有方案，conclusion 会退化成「待补充信息」，
        # 用回答正文补足——否则下一轮回看历史只知道「答过」，不知道「答了什么」。
        "reply": _clip(reply, _REPLY_SUMMARY_LIMIT),
        "steps": steps[:_SUMMARY_STEPS_LIMIT],
        # 观测数据（2026-11-05）：六维快照与断言对账随摘要落库，供离线统计阈值用；
        # 上下文装配只按字段取用既有键，故不影响 prompt 与 API 响应。
        "level": str(data.get("level", "")),
        "claims": claims,
        "sensorium": sensorium,
    }
