"""JevDecider：DecisionPort 的 Jev 实现（F-202；MUST-12 双路径同构）。

typesafe-sdk 0.7.2 API 核实结论（D-5E-1，2026-10-10 实测，版本见 pyproject jev extra）：
- `AsyncTypeSafeClient.system_one(state, questions)`：单次调用并行回答全部命名问题
  （契合 F-202「单次调用内并行提出全部问题，不做多次往返」）。
- 问题原语：Noul（0..1 概率）/ Choice（命名选择 + confidence）/ Score（有序刻度 + confidence）。
- 429 识别：TypeSafeRateLimitError；SDK 内置 RetryPolicy 以 max_retries=0 关闭，
  退避序列由本模块手写（F-202：0.5 × 2^n，n ≤ 4）。
- SDK 默认模型 "jev-latest" 正是别名（印证 MUST-12 禁别名）：必须显式传 JEV_MODEL_ID。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Literal, Protocol, cast

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    Question,
    RetryPolicy,
    Score,
    SystemOneResponse,
    TypeSafeRateLimitError,
)

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import (
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.errors import ConfigurationError
from devprompt_ai.domain.models import Candidate, FactResult

JEV_MODEL_ID = "jev-1.13.0"
"""钉死的 Jev 模型 ID（MUST-12）：禁用别名——别名随上游漂移会让置信度阈值失效。"""

logger = logging.getLogger("devprompt.decision")

_RETRY_COUNT = 5
"""429 重试次数上限：n = 0..4（F-202 退避序列 0.5 × 2^n，n ≤ 4；重试耗尽抛原异常）。"""

_RETRY_INITIAL_DELAY = 0.5

_SCORE_RUBRIC: tuple[str, ...] = (
    "0：完全不适配，与需求无关",
    "1：存在误导风险，方向错误",
    "2：方向正确但需大幅编辑",
    "3：方向正确仅需少量微调",
    "4：完美适配，可直接使用",
)
"""五档评分刻度文案（F-401，与 fallback SCORE_SYSTEM 语义一致）；按「每级一条、从 0 起」传参。"""


class JevTransport(Protocol):
    """传输层抽象（构造注入）：生产用 AsyncTypeSafeClient，测试注入 fake 不触网。"""

    async def system_one(
        self, state: str, questions: Mapping[str, Question], *, model: str
    ) -> SystemOneResponse: ...


def _estimate_tokens(text: str) -> int:
    """token 粗估（保守上界，MUST-04 标准库实现）：CJK 字符 ≈ 1 token，其余 4 字符 ≈ 1 token。"""
    cjk = sum(1 for ch in text if ch > "\\u2e7f")
    return cjk + (len(text) - cjk) // 4


class JevDecider:
    """F-202 三类决策能力的 Jev 版本；输出结构与 LLMFallbackDecider 完全一致（MUST-12）。"""

    def __init__(self, cfg: AppConfig, transport: JevTransport | None = None) -> None:
        if cfg.jev_model_id != JEV_MODEL_ID:
            raise ConfigurationError(
                f"jev_model_id 必须为 {JEV_MODEL_ID}，禁用别名（MUST-12）",
                context={"jev_model_id": cfg.jev_model_id},
            )
        self._cfg = cfg
        self._transport: JevTransport | None = transport

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        if not candidates:
            # 空问题集会被 API 拒绝；空候选集语义上不存在排序，直接返回空结果
            return RankComponentsOutput(order=[], confidence=0.0)
        questions: dict[str, Question] = {
            f"candidate_{i}": Noul(
                instructions=f"用户想修改的目标是否是符号「{c.name}」（路径 {c.path}）？"
            )
            for i, c in enumerate(candidates)
        }
        # state 仅含原句与符号名/路径，不含代码正文（MUST-09）
        resp = await self._ask(sentence, questions)
        # noul 即 0..1 概率（SDK 直返，不做本地二次加工）；按概率降序产出 order 为确定性映射
        probabilities = [resp.nouls[f"candidate_{i}"].noul for i in range(len(candidates))]
        order = sorted(range(len(probabilities)), key=probabilities.__getitem__, reverse=True)
        return RankComponentsOutput(order=order, confidence=probabilities[order[0]])

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        if not facts:
            return FactProbeOutput(judgments=[], overall_confidence=0.0)
        listing = "\\n".join(
            f"- {f.key}: {'真' if f.passed else '假'}（证据：{f.evidence}）" for f in facts
        )
        state = f"用户需求：{sentence}\\n\\n取证结果：\\n{listing}"
        questions: dict[str, Question] = {
            f"fact_{i}": Choice(
                instructions=f"综合用户需求判断：事实「{f.key}」是否成立？",
                criteria={"true": None, "false": None},
            )
            for i, f in enumerate(facts)
        }
        resp = await self._ask(state, questions)
        # confidence 直接采用 SDK 返回值（F-202：置信度全部返回，不做本地二次加工）
        judgments = [
            FactJudgment(
                key=f.key,
                passed=resp.choices[f"fact_{i}"].choice == "true",
                confidence=resp.choices[f"fact_{i}"].confidence,
            )
            for i, f in enumerate(facts)
        ]
        # Jev 无「综合置信度」原语：以各问 confidence 均值合成（输出结构适配，非置信度再加工）
        overall = sum(j.confidence for j in judgments) / len(judgments)
        return FactProbeOutput(judgments=judgments, overall_confidence=overall)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        if not variants:
            return ScorePromptsOutput(scores=[])
        listing = "\\n\\n".join(f"【方案 {key}】\\n{body}" for key, body in variants)
        state = f"项目上下文：{context}\\n\\n待评方案：\\n{listing}"
        questions: dict[str, Question] = {
            f"variant_{key}": Score(
                instructions=f"评估方案 {key} 对项目上下文的适配度（0~4 五档）",
                criteria=list(_SCORE_RUBRIC),
            )
            for key, _ in variants
        }
        resp = await self._ask(state, questions)
        # Score 原语返回概率加权期望分（可落在两档之间）；F-401 契约要求整数档 → round 收窄。
        # variant 的 Literal 收窄由 pydantic 校验兜底（非法档位构造即 ValidationError）
        scores = [
            VariantScore(
                variant=cast(Literal["A", "B", "C"], key),
                score=round(resp.scores[f"variant_{key}"].score),
                confidence=resp.scores[f"variant_{key}"].confidence,
            )
            for key, _ in variants
        ]
        return ScorePromptsOutput(scores=scores)

    async def _ask(self, state: str, questions: Mapping[str, Question]) -> SystemOneResponse:
        """单次 system_one 调用 + 429 手写指数退避（F-202；MUST-13：async sleep 非阻塞）。"""
        transport = self._ensure_transport()
        fitted = self._fit_state(state)
        attempt = 0
        while True:
            try:
                return await transport.system_one(
                    state=fitted, questions=questions, model=JEV_MODEL_ID
                )
            except TypeSafeRateLimitError:
                if attempt >= _RETRY_COUNT:
                    raise  # 重试耗尽抛原异常（F-202）
                await asyncio.sleep(_RETRY_INITIAL_DELAY * (2**attempt))
                attempt += 1

    def _fit_state(self, state: str) -> str:
        """state 组装硬限（F-202 / MUST-09）：超 max_state_tokens 截断而非报错，记 state.truncated。

        截断保留头部（用户需求/上下文在前，牺牲尾部正文完整性优先保证调用不失败）；
        截到 max_tokens 字符后按粗估上界必然不超限（全 CJK 时恰好等于上限）。
        """
        limit = self._cfg.max_state_tokens
        estimated = _estimate_tokens(state)
        if estimated <= limit:
            return state
        logger.warning(
            "state.truncated reason=state-over-limit estimated_tokens=%d limit=%d",
            estimated,
            limit,
        )
        return state[:limit]

    def _ensure_transport(self) -> JevTransport:
        """惰性创建 SDK 客户端（进程生命周期复用）；已注入 transport（测试）则直接用。"""
        if self._transport is None:
            # SDK 内置重试关闭：429 退避由 _ask 手写（F-202 显式序列，MUST-04 不引新依赖）
            self._transport = AsyncTypeSafeClient(
                api_key=self._cfg.typesafe_api_key,
                model=JEV_MODEL_ID,
                retry=RetryPolicy(max_retries=0),
            )
        return self._transport
