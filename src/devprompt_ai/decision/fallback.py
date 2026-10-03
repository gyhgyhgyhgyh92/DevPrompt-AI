"""LLMFallbackDecider：DecisionPort 的 LLM 实现（F-201；无 Jev 密钥时的默认实现，MUST-12）。"""

from __future__ import annotations

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
        )


def create_decider(cfg: AppConfig) -> DecisionPort:
    """决策层工厂（MUST-12 可降级结构）：Jev 密钥存在且 decider=jev → JevDecider（阶段五实现，
    本阶段返回 LLM 版并在日志记 decider.switched 原因=jev-not-available）；否则 LLM 版。"""
    # 阶段五 T5-9 替换此工厂的 Jev 分支；本阶段只有 LLM 路径。
    return LLMFallbackDecider(cfg)
