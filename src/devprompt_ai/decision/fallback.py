"""LLMFallbackDecider：DecisionPort 的唯一 LLM 实现（F-201；MUST-12）。

2026-10-15 起决策层为单一 LLM 实现（原 MUST-12 双路径已按所有者批准废除）。
create_decider 保留函数名与签名（调用方零改动），恒返回 LLMFallbackDecider。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Final

from devprompt_ai.common.text import estimate_tokens
from devprompt_ai.config import AppConfig
from devprompt_ai.decision.prompts import (
    ACTION_LINES,
    FACTS_SYSTEM,
    FACTS_USER,
    NEXT_ACTION_USER,
    RANK_SYSTEM,
    RANK_USER,
    SCORE_SYSTEM,
    SCORE_USER,
    facts_evidence,
    next_action_enum,
    next_action_system,
    plan_evidence,
    rank_evidence,
    score_evidence,
)
from devprompt_ai.domain.agent.action import AgentAction, AgentStep
from devprompt_ai.domain.decision.port import (
    DecisionPort,
    FactProbeOutput,
    NextActionOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.models import Candidate, FactResult
from devprompt_ai.domain.retrieval.query_rewrite import QueryRewriteOutput, RewrittenQuery
from devprompt_ai.harness.ask_tool import parse_ask_call
from devprompt_ai.harness.guardrails import validate_ranking
from devprompt_ai.harness.llm import (
    chat_structured,
    chat_with_tools,
    parse_structured,
)
from devprompt_ai.observability.logging import emit, emit_warning

logger = logging.getLogger("devprompt.decision")

#: 动作枚举全集（含 delegate）：allowed_actions=None 时 USER 枚举串与旧契约逐字一致。
_ALL_ACTIONS: Final[tuple[str, ...]] = tuple(ACTION_LINES) + ("delegate",)

#: 结构化 Query 改写（2026-11-19）：多轮追问换目标时，规则识别不出纯中文描述。
REWRITE_SYSTEM: Final[str] = (
    "你是检索查询分析器。判断用户这一轮想改的目标是否与上一轮相同。"
    "只输出 JSON：target（目标名，沿用则原样给出上一轮目标）、intent"
    "（add/modify/remove/diagnose）、entities（提到的组件/页面/样式等实体）、"
    "negation（明确不要的东西）、confidence（0~1，指目标判断的把握）。"
)
REWRITE_USER: Final[str] = (
    "上一轮目标：{previous}\n本轮原句：{sentence}\n\n"
    "如果本轮只是改样式/参数/细节，target 保持上一轮；"
    "如果说的是另一个页面、组件或模块，target 写新目标名。"
)


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


def _candidate_line(index: int, candidate: Candidate) -> str:
    """候选行：名称 + 路径 + 签名（签名非空才附）。

    签名是排序阶段唯一缺失的判别性上下文（W3 实测：仅名称与路径时 top-1 命中 58%）。
    只带签名、不带函数体（MUST-09 硬边界不变）。
    """
    base = f"{index}. {candidate.name}  ({candidate.path})"
    return f"{base}  {candidate.signature}" if candidate.signature else base


class LLMFallbackDecider:
    """三类能力同构：单次调用 + 结构化输出。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        listing = "\n".join(_candidate_line(i, c) for i, c in enumerate(candidates))
        # timeout 缺省即 cfg.llm_timeout（F-604 默认 60s；25 候选大 prompt 10s 必超时——实测）
        user = _fit_state(
            RANK_USER.format(evidence=rank_evidence(sentence, listing)),
            self._cfg.runtime_state_budget(),
        )
        out = await chat_structured(
            self._cfg,
            RankComponentsOutput,
            RANK_SYSTEM,
            user,
            timeout=self._cfg.llm_rank_timeout,
            purpose="rank",
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
            self._cfg.runtime_state_budget(),
        )
        if answered:
            block = "\n".join(f"- 问：{q}\n  答：{a}" for q, a in answered.items())
            user = f"{user}\n\n【已确认的问答（不要再问这些）】\n{block}"

        try:
            result = await chat_with_tools(
                self._cfg,
                FACTS_SYSTEM,
                user,
                timeout=self._cfg.llm_probe_timeout,
                purpose="probe",
            )
        except DevPromptError as exc:
            emit_warning("decision.tools_unsupported", reason=type(exc).__name__)
            return await chat_structured(
                self._cfg,
                FactProbeOutput,
                FACTS_SYSTEM,
                user,
                timeout=self._cfg.llm_probe_timeout,
                purpose="probe",
            )

        if result.tool_call is not None:
            ask = parse_ask_call(result.tool_call.arguments)
            if ask is None:
                emit_warning("decision.ask_args_invalid", call_id=result.tool_call.call_id)
                return FactProbeOutput(
                    judgments=[],
                    overall_confidence=None,
                    confidence_source="no_data",
                    questions=[],
                    ask_call_id=result.tool_call.call_id,
                )
            # 2026-11-04：模型走工具调用时并未给出置信度——True 是「未给判断」而非「判断为 0」。
            # 此前强制 0.0 让下游把它当低置信，等价于「问了问题就永远升不到 C 档」。
            return FactProbeOutput(
                judgments=[],
                overall_confidence=None,
                confidence_source="no_data",
                questions=ask.questions,
                task_kind=ask.task_kind,
                ask_call_id=result.tool_call.call_id,
            )

        parsed = parse_structured(FactProbeOutput, result.text)
        if parsed is not None:
            return parsed
        # 文本不是合法 JSON：退回结构化调用（自带纠偏重试与错误码细分）
        return await chat_structured(
            self._cfg,
            FactProbeOutput,
            FACTS_SYSTEM,
            user,
            timeout=self._cfg.llm_probe_timeout,
            purpose="probe",
        )

    async def rewrite_query(self, sentence: str, previous_target: str = "") -> RewrittenQuery:
        """LLM 结构化改写（2026-11-19）：失败向上抛，由调用方回退规则结果。"""
        user = REWRITE_USER.format(
            previous=previous_target or "（无）", sentence=sentence[:500]
        )
        out = await chat_structured(
            self._cfg,
            QueryRewriteOutput,
            REWRITE_SYSTEM,
            user,
            timeout=self._cfg.llm_probe_timeout,
            purpose="probe",
        )
        return RewrittenQuery(
            target=(out.target or previous_target).strip()[:80],
            intent=out.intent or "modify",
            entities=tuple(str(item)[:40] for item in out.entities[:8]),
            negation=tuple(str(item)[:40] for item in out.negation[:8]),
            confidence=max(0.0, min(1.0, float(out.confidence))),
        )

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        listing = "\n\n".join(f"【方案 {key}】\n{body}" for key, body in variants)
        user = _fit_state(
            SCORE_USER.format(evidence=score_evidence(context, listing)),
            self._cfg.runtime_state_budget(),
        )
        return await chat_structured(
            self._cfg,
            ScorePromptsOutput,
            SCORE_SYSTEM,
            user,
            timeout=self._cfg.llm_rank_timeout,
            purpose="rank",
        )

    async def next_action(
        self,
        *,
        sentence: str,
        facts: Sequence[FactResult],
        steps: Sequence[AgentStep],
        variant_count: int,
        clarifications: Mapping[str, str],
        correction: str = "",
        inherited_variant_count: int = 0,
        allowed_actions: Sequence[AgentAction] | None = None,
    ) -> NextActionOutput:
        """Agentic 调度：给定已发生的事实与动作序列，决定下一步做什么。

        与前三类能力的区别：它消费的是「本轮已走到哪」，不是「这组输入怎么判」。
        同样单次调用 + 结构化输出，不加调用轮次。
        ``allowed_actions``（2026-11-14 领域包）：None 表示全部动作（旧调用方零改动）；
        非空时 SYSTEM 菜单与 USER 枚举串只列白名单动作。
        """
        allowed = (
            [a.value for a in allowed_actions]
            if allowed_actions is not None
            else list(next_action_enum(_ALL_ACTIONS))
        )
        fact_listing = "\n".join(
            f"- {f.key}: {'真' if f.passed else '假'}（证据：{f.evidence}）" for f in facts
        )
        step_listing = "\n".join(
            f"{s.index + 1}. {s.action.value} → {s.outcome.value}"
            + (f"（{s.note}）" if s.note else "")
            for s in steps
        )
        clarification_listing = "\n".join(f"- {q}：{a}" for q, a in clarifications.items())
        # 白名单经 USER 枚举串二次注入（SYSTEM 菜单已过滤）；replace 而非 format，
        # 避免与 NEXT_ACTION_USER 既有的 {evidence} 占位相互干扰。
        user_template = NEXT_ACTION_USER.replace(
            '"retrieve|probe|ask|generate|deliver|abort|reply|delegate"',
            f'"{next_action_enum(allowed)}"',
        )
        user = _fit_state(
            user_template.format(
                evidence=plan_evidence(
                    sentence,
                    fact_listing,
                    step_listing,
                    variant_count,
                    clarification_listing,
                    correction,
                    inherited_variant_count,
                )
            ),
            self._cfg.runtime_state_budget(),
        )
        return await chat_structured(
            self._cfg,
            NextActionOutput,
            next_action_system(allowed),
            user,
            timeout=self._cfg.llm_rank_timeout,
            purpose="decide",
        )


def create_decider(cfg: AppConfig) -> DecisionPort:
    """决策层工厂：恒返回 LLMFallbackDecider（原 MUST-12 双路径已按所有者批准废除）。"""
    return LLMFallbackDecider(cfg)
