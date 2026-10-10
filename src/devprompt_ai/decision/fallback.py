"""LLMFallbackDecider：DecisionPort 的 LLM 实现（F-201；无 Jev 密钥时的默认实现，MUST-12）。

create_decider 工厂提供双路径（T5-9）：有 TYPESAFE_API_KEY → JevDecider（外层套
FailoverDecider 失败切换），无 key 或 decider=fallback → 本模块 LLM 版。
"""

from __future__ import annotations

import logging

from devprompt_ai.config import AppConfig
from devprompt_ai.decision.prompts import (
    FACTS_SYSTEM,
    FACTS_USER,
    RANK_SYSTEM,
    RANK_USER,
    SCORE_SYSTEM,
    SCORE_USER,
)
from devprompt_ai.domain.decision.port import (
    DecisionPort,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.models import Candidate, FactResult
from devprompt_ai.harness.guardrails import validate_ranking
from devprompt_ai.harness.llm import chat_structured

logger = logging.getLogger("devprompt.decision")

_MAX_CONSECUTIVE_FAILURES = 3
"""Jev 主路径连续失败次数阈值（MUST-12：连续失败自动切 LLM 版）。"""


class LLMFallbackDecider:
    """三类能力同构：单次调用 + 结构化输出；输出结构与 Jev 版完全一致（MUST-12）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        listing = "\n".join(f"{i}. {c.name}  ({c.path})" for i, c in enumerate(candidates))
        out = await chat_structured(
            self._cfg,
            RankComponentsOutput,
            RANK_SYSTEM,
            RANK_USER.format(sentence=sentence, candidates=listing),
            timeout=60.0,  # 25 候选大 prompt，DeepSeek 实测 10s 必超时（排序准确率实测暴露）
        )
        validate_ranking(out, len(candidates))
        return out

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        listing = "\n".join(
            f"- {f.key}: {'真' if f.passed else '假'}（证据：{f.evidence}）" for f in facts
        )
        return await chat_structured(
            self._cfg,
            FactProbeOutput,
            FACTS_SYSTEM,
            FACTS_USER.format(sentence=sentence, facts=listing),
        )

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        listing = "\n\n".join(f"【方案 {key}】\n{body}" for key, body in variants)
        return await chat_structured(
            self._cfg,
            ScorePromptsOutput,
            SCORE_SYSTEM,
            SCORE_USER.format(context=context, variants=listing),
            timeout=60.0,  # 三套长正文，同生成类放宽
        )


class FailoverDecider:
    """MUST-12 可降级：Jev 主路径连续 3 次失败 → 永久切 LLM 版并记 decider.switched（带原因）。

    失败计数与切换包在 primary 外层（不侵入两种实现）；切换后不回切，避免在
    Jev 抖动场景下反复震荡。单流程内 decider 调用串行（MUST-11），计数无并发竞争。
    """

    def __init__(
        self, primary: DecisionPort, cfg: AppConfig, max_failures: int = _MAX_CONSECUTIVE_FAILURES
    ) -> None:
        self._primary = primary
        self._cfg = cfg
        self._max_failures = max_failures
        self._consecutive_failures = 0
        self._delegate: LLMFallbackDecider | None = None

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        if self._delegate is not None:
            return await self._delegate.rank_components(sentence, candidates)
        try:
            out = await self._primary.rank_components(sentence, candidates)
        except Exception:
            self._register_failure()
            raise
        self._reset_failures()
        return out

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        if self._delegate is not None:
            return await self._delegate.probe_facts(sentence, facts)
        try:
            out = await self._primary.probe_facts(sentence, facts)
        except Exception:
            self._register_failure()
            raise
        self._reset_failures()
        return out

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        if self._delegate is not None:
            return await self._delegate.score_prompts(context, variants)
        try:
            out = await self._primary.score_prompts(context, variants)
        except Exception:
            self._register_failure()
            raise
        self._reset_failures()
        return out

    def _register_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_failures:
            self._delegate = LLMFallbackDecider(self._cfg)
            logger.warning(
                "decider.switched reason=jev-consecutive-failures consecutive_failures=%d",
                self._consecutive_failures,
            )

    def _reset_failures(self) -> None:
        self._consecutive_failures = 0


def create_decider(cfg: AppConfig) -> DecisionPort:
    """决策层工厂（MUST-12 双路径）：有 TYPESAFE_API_KEY 且 decider≠fallback → Jev
    （外层套 FailoverDecider，连续 3 次失败自动切 LLM 版并记 decider.switched）；
    否则 LLM 版。显式 decider=jev 而无 key 时降级并记切换原因。

    JevDecider 延迟导入：无 key 环境（未装 jev extra）不触发 typesafe_sdk 依赖。
    """
    if cfg.typesafe_api_key and cfg.decider != "fallback":
        from devprompt_ai.decision.jev import JevDecider

        return FailoverDecider(JevDecider(cfg), cfg)
    if cfg.decider == "jev":
        logger.warning("decider.switched reason=jev-no-api-key")
    return LLMFallbackDecider(cfg)
