"""F-201 决策层接口：三类能力 + 统一输出结构（形态无关，MUST-12）。

输出用 pydantic 模型（openai-agents output_type 要求），校验规则内聚：
排序必须是 0..n-1 的排列、置信度 ∈ [0,1]、Score ∈ [0,4]。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator, model_validator

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
    #: 当前最佳推断（MUST-26：每问必须给出）。为空时由 build_unknowns 回退到同 key 的取证证据。
    best_guess: str = ""


class FactProbeOutput(BaseModel):
    judgments: list[FactJudgment]
    #: 模型自报置信度。None = 模型未给判断（与「判断为 0」是两件事，2026-11-04）。
    overall_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: 置信度来源。缺省由 whether overall_confidence is None 推断，避免旧输出被迫改造。
    confidence_source: Literal["measured", "no_data"] | None = None
    #: 模型决定「问不问、问几个」；空表示当前信息已够，直接生成（不机械追问）。
    questions: list[AskQuestion] = Field(default_factory=list)
    #: AskUserQuestion 的 call_id（来自 function_call，仅用于审计/追踪）
    ask_call_id: str = ""
    #: 决策层自判的任务类型：design = 原句模糊需深挖 5 类；execution = 范围已知走闸门。
    #: 缺省 execution 保证旧 mock / 旧输出零改动。
    task_kind: Literal["design", "execution"] = "execution"

    @model_validator(mode="after")
    def _infer_confidence_source(self) -> FactProbeOutput:
        """缺省来源按「有没有值」推断；显式给 measured 却没有值视为契约破坏。"""
        if self.confidence_source is None:
            self.confidence_source = (
                "measured" if self.overall_confidence is not None else "no_data"
            )
        if self.confidence_source == "measured" and self.overall_confidence is None:
            raise ValueError("confidence_source=measured 时 overall_confidence 不得为 None")
        return self


class DelegationOrderDraft(BaseModel):
    """决策层下发的委派工单草案（K6 多波来源）。

    只读两档（K4 边界：patcher 写工不下发）；id 由 service 按序补齐，
    ``dependencies`` 引用其它草案的**序号**（"0"/"1"…），service 负责换成工单 id。
    """

    profile: Literal["code_scout", "verifier"] = "code_scout"
    objective: str = Field(min_length=1, max_length=300)
    scope_files: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()


class NextActionOutput(BaseModel):
    """Agentic 循环的下一步动作（F-201 扩展）。

    ``action`` 用字面量而非 import AgentAction：决策层不该知道 agent 包的内部枚举，
    由 service 在分发时做一次转换。
    """

    action: Literal[
        "retrieve",
        "probe",
        "ask",
        "generate",
        "rank",
        "deliver",
        "abort",
        "reply",
        "delegate",
    ]
    reason: str = ""
    #: 本次决策的实测置信度；模型未给判断时为 None（与 FactProbeOutput 同一约定）。
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_source: Literal["measured", "no_data"] = "measured"
    #: K6 多波来源：action=delegate 时可下发工单列表；空缺时 service 走确定性单工单
    delegation_orders: tuple[DelegationOrderDraft, ...] = ()

    @model_validator(mode="after")
    def _measured_requires_value(self) -> NextActionOutput:
        if self.confidence_source == "measured" and self.confidence is None:
            raise ValueError("confidence_source=measured 时 confidence 不得为 None")
        return self


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

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        """事实研判：取证结果 + 原句 → 判定 + 置信度 + 可选提问。

        ``answered`` 是已确认的问答（question 原文 → 答案），重建 prompt 时注入，
        让模型不要重复提问（anthropic/gemini 原生适配器不支持回喂 tool result，故重建）。
        """
        ...

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        """方案打分：上下文 + [(档位, 正文)] → 三档适配度（阶段五接入）。"""
        ...
