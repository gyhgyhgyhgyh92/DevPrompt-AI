"""F-201 决策层接口：三类能力 + 统一输出结构（形态无关，MUST-12）。

输出用 pydantic 模型（openai-agents output_type 要求），校验规则内聚：
排序必须是 0..n-1 的排列、置信度 ∈ [0,1]、Score ∈ [0,4]。
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from devprompt_ai.domain.models import Candidate, FactResult


class RankComponentsOutput(BaseModel):
    """组件排序输出：order 为候选索引（按最优在前），confidence ∈ [0,1]。"""

    order: list[int]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("order")
    @classmethod
    def _order_must_be_permutation(cls, v: list[int]) -> list[int]:
        if sorted(v) != list(range(len(v))):
            raise ValueError(f"order 必须是 0..n-1 的排列，实际 {v}")
        return v


class FactJudgment(BaseModel):
    key: str
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)


class FactProbeOutput(BaseModel):
    judgments: list[FactJudgment]
    overall_confidence: float = Field(ge=0.0, le=1.0)


class VariantScore(BaseModel):
    variant: Literal["A", "B", "C"]
    score: int = Field(ge=0, le=4)  # F-401 五档刻度
    confidence: float = Field(ge=0.0, le=1.0)


class ScorePromptsOutput(BaseModel):
    scores: list[VariantScore]


@runtime_checkable
class DecisionPort(Protocol):
    """三类决策能力（F-201 职责表）。

    实现：decision/fallback.py（LLM）、decision/jev.py（阶段五）。
    """

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        """组件排序：原句 + 候选（仅符号名+路径，MUST-09 顺序：候选已在检索段压好）。"""
        ...

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        """事实研判：取证结果 + 原句 → 各项判定 + 综合置信度。"""
        ...

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        """方案打分：上下文 + [(档位, 正文)] → 三档适配度（阶段五接入）。"""
        ...
