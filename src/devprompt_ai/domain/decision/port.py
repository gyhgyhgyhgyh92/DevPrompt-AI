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


class AskOption(BaseModel):
    """反问选项（对齐 CodeBuddy SDK `AskUserQuestion` 的 options[]）。"""

    label: str
    description: str = ""


class AskQuestion(BaseModel):
    """决策层主动提出的一问：key 绑定具体未知项，问法与选项由模型给出。

    对齐官方形态（question / header / options / multiSelect），同时保留 ``key``
    以满足 MUST-26「每问绑定具体未知项」——答案仍按 key 回填 clarifications。
    """

    key: str
    question: str
    header: str = ""
    options: list[AskOption] = Field(default_factory=list)
    multi_select: bool = False


class FactProbeOutput(BaseModel):
    judgments: list[FactJudgment]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    #: 模型决定「问不问、问几个」；空表示当前信息已够，直接生成（不机械追问）。
    questions: list[AskQuestion] = Field(default_factory=list)
    #: 决策层自判的任务类型：design = 原句模糊需深挖 5 类；execution = 范围已知走闸门。
    #: 缺省 execution 保证旧 mock / 旧输出零改动。
    task_kind: Literal["design", "execution"] = "execution"


class VariantScore(BaseModel):
    variant: Literal["A", "B", "C"]
    score: int = Field(ge=0, le=4)  # F-401 五档刻度
    confidence: float = Field(ge=0.0, le=1.0)


class ScorePromptsOutput(BaseModel):
    scores: list[VariantScore]


@runtime_checkable
class DecisionPort(Protocol):
    """三类决策能力（F-201 职责表）。

    实现：decision/fallback.py（LLM）。
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
