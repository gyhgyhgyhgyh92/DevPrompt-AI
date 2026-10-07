"""F-204 v1.1 自适应反问编排：unknowns 构建 + 软护栏状态（纯逻辑零 I/O，MUST-06）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from devprompt_ai.domain.decision.port import FactProbeOutput
from devprompt_ai.domain.decision.probes import PROBE_ASK_TEXT
from devprompt_ai.domain.models import FactResult

_EVIDENCE_LIMIT = 120


class GuardrailConfig(Protocol):
    """护栏阈值契约（结构类型）：AppConfig 天然满足。

    domain 不 import devprompt_ai.config（check_architecture MUST-06 门禁），只声明所需能力。
    """

    @property
    def followup_soft_round_guard(self) -> int: ...

    @property
    def followup_cost_budget(self) -> float: ...


@dataclass(frozen=True, slots=True)
class UnknownItem:
    """具体未决事实（MUST-26 v1.1）：每问绑定一项。"""

    key: str
    reason: str
    best_guess: str
    ask: str


def build_unknowns(
    probe: FactProbeOutput,
    facts: Sequence[FactResult],
    *,
    clarifications: dict[str, str] | None = None,
) -> list[UnknownItem]:
    """失败或低置信的事实 → 未知项；用户已答复的 key 视为已澄清跳过。"""
    clar = clarifications or {}
    judgment_by_key = {j.key: j for j in probe.judgments}
    items: list[UnknownItem] = []
    for fact in facts:
        if fact.key in clar:
            continue  # 已澄清（MUST-26：答复即解除该未知项）
        judgment = judgment_by_key.get(fact.key)
        if fact.passed and (judgment is None or judgment.passed):
            continue
        reason = (
            fact.evidence
            if not fact.passed
            else (f"研判置信度不足（{judgment.confidence:.2f}）" if judgment else "未判定")
        )
        items.append(
            UnknownItem(
                key=fact.key,
                reason=reason[:_EVIDENCE_LIMIT],
                best_guess=fact.evidence[:_EVIDENCE_LIMIT] if fact.passed else "",
                ask=PROBE_ASK_TEXT.get(fact.key, fact.key),
            )
        )
    return items


@dataclass(slots=True)
class GuardrailState:
    """MUST-26 软护栏：触发时不静默终止，由 service 转为显式用户裁决。"""

    rounds: int = 0
    cost_tokens: int = 0

    def should_trigger(self, cfg: GuardrailConfig) -> bool:
        if self.rounds >= cfg.followup_soft_round_guard:
            return True
        return cfg.followup_cost_budget > 0 and self.cost_tokens >= cfg.followup_cost_budget

    def reset(self) -> None:
        """用户裁决「继续追问」后清零。"""
        self.rounds = 0
        self.cost_tokens = 0
