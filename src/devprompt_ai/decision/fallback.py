"""LLMFallbackDecider：DecisionPort 的唯一 LLM 实现（F-201；MUST-12）。

2026-10-15 起决策层为单一 LLM 实现（原 MUST-12 双路径已按所有者批准废除）。
create_decider 保留函数名与签名（调用方零改动），恒返回 LLMFallbackDecider。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from devprompt_ai.common.text import estimate_tokens
from devprompt_ai.config import AppConfig
from devprompt_ai.decision.prompts import (
    FACTS_SYSTEM,
    FACTS_USER,
    RANK_SYSTEM,
    RANK_USER,
    SCORE_SYSTEM,
    SCORE_USER,
    facts_evidence,
    rank_evidence,
    score_evidence,
)
from devprompt_ai.domain.decision.port import (
    DecisionPort,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.models import Candidate, FactResult
from devprompt_ai.harness.ask_tool import parse_ask_call
from devprompt_ai.harness.guardrails import validate_ranking
from devprompt_ai.harness.llm import (
    chat_structured,
    chat_with_tools,
    parse_structured,
)
from devprompt_ai.observability.logging import emit, emit_warning

logger = logging.getLogger("devprompt.decision")


def _fit_state(text: str, limit: int) -> str:
    """state 提交前预校验长度（MUST-09）：超限保留头部截断并记 state.truncated。

    保留头部理由：用户需求与上下文在最前，截尾对决策语义损失最小（与移除前 jev.py
    同一取舍）。未超限原样返回，不改动 state。截断到粗估 token ≤ limit 的最长前缀。
    """
    estimated = estimate_tokens(text)
    if estimated <= limit:
        return text
    emit(
        "state.truncated",
        reason="state-over-limit",
        estimated_tokens=estimated,
        limit=limit,
    )
    # estimate_tokens 随前缀单调不减，二分定位仍 ≤ limit 的最长前缀
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


class LLMFallbackDecider:
    """三类能力同构：单次调用 + 结构化输出。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        listing = "\n".join(f"{i}. {c.name}  ({c.path})" for i, c in enumerate(candidates))
        # timeout 缺省即 cfg.llm_timeout（F-604 默认 60s；25 候选大 prompt 10s 必超时——实测）
        user = _fit_state(
            RANK_USER.format(evidence=rank_evidence(sentence, listing)),
            self._cfg.max_state_tokens,
        )
        out = await chat_structured(
            self._cfg,
            RankComponentsOutput,
            RANK_SYSTEM,
            user,
        )
        validate_ranking(out, len(candidates))
        return out

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        """研判：走 AskUserQuestion 工具调用；模型不调工具时解析 JSON。

        降级：任一 provider 报错（含不支持 tools）→ 回落 ``chat_structured`` 且本轮不提问，
        并发 ``decision.tools_unsupported`` 告警（不静默 500）。
        """
        listing = "\n".join(
            f"- {f.key}: {'真' if f.passed else '假'}（证据：{f.evidence}）" for f in facts
        )
        user = _fit_state(
            FACTS_USER.format(evidence=facts_evidence(sentence, listing)),
            self._cfg.max_state_tokens,
        )
        if answered:
            block = "\n".join(f"- 问：{q}\n  答：{a}" for q, a in answered.items())
            user = f"{user}\n\n【已确认的问答（不要再问这些）】\n{block}"

        try:
            result = await chat_with_tools(self._cfg, FACTS_SYSTEM, user)
        except DevPromptError as exc:
            emit_warning("decision.tools_unsupported", reason=type(exc).__name__)
            return await chat_structured(self._cfg, FactProbeOutput, FACTS_SYSTEM, user)

        if result.tool_call is not None:
            ask = parse_ask_call(result.tool_call.arguments)
            if ask is None:
                emit_warning("decision.ask_args_invalid", call_id=result.tool_call.call_id)
                return FactProbeOutput(
                    judgments=[],
                    overall_confidence=0.0,
                    questions=[],
                    ask_call_id=result.tool_call.call_id,
                )
            return FactProbeOutput(
                judgments=[],
                overall_confidence=0.0,
                questions=ask.questions,
                task_kind=ask.task_kind,
                ask_call_id=result.tool_call.call_id,
            )

        parsed = parse_structured(FactProbeOutput, result.text)
        if parsed is not None:
            return parsed
        # 文本不是合法 JSON：退回结构化调用（自带纠偏重试与错误码细分）
        return await chat_structured(self._cfg, FactProbeOutput, FACTS_SYSTEM, user)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        listing = "\n\n".join(f"【方案 {key}】\n{body}" for key, body in variants)
        user = _fit_state(
            SCORE_USER.format(evidence=score_evidence(context, listing)),
            self._cfg.max_state_tokens,
        )
        return await chat_structured(
            self._cfg,
            ScorePromptsOutput,
            SCORE_SYSTEM,
            user,
        )


def create_decider(cfg: AppConfig) -> DecisionPort:
    """决策层工厂：恒返回 LLMFallbackDecider（原 MUST-12 双路径已按所有者批准废除）。"""
    return LLMFallbackDecider(cfg)
