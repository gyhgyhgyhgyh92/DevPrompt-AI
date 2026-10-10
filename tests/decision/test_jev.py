"""JevDecider 行为测试（T5-9）：fake transport 不触网；429 退避 monkeypatch asyncio.sleep。

无 key 环境全链路可跑（SHOULD-11）：全部用例不发起真实网络请求。
"""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel
from typesafe_sdk import (
    ChoiceAnswer,
    NoulAnswer,
    Question,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeRateLimitError,
    Usage,
)

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import fallback as fb
from devprompt_ai.decision.fallback import (
    FailoverDecider,
    LLMFallbackDecider,
    create_decider,
)
from devprompt_ai.decision.jev import JEV_MODEL_ID, JevDecider, _estimate_tokens
from devprompt_ai.domain.decision.port import (
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.errors import ConfigurationError, GenerationError
from devprompt_ai.domain.models import Candidate, FactResult

_RATE_LIMITED = TypeSafeRateLimitError(429, {}, httpx2.Headers({}), "rate limited")


def _cfg(**overrides: Any) -> AppConfig:
    return AppConfig(_env_file=None, typesafe_api_key="test-key", **overrides)  # type: ignore[call-arg]


def _cands() -> list[Candidate]:
    return [
        Candidate(name="Button", path="src/ui.tsx", line=1, score=2.0, source="symbol"),
        Candidate(name="Panel", path="src/panel.tsx", line=1, score=1.0, source="symbol"),
    ]


def _facts() -> list[FactResult]:
    return [
        FactResult(key="target_file_exists", passed=True, evidence="file=src/ui.tsx"),
        FactResult(key="token_defined", passed=False, evidence="no match"),
    ]


def _resp(answers: dict[str, Any]) -> SystemOneResponse:
    return SystemOneResponse(model=JEV_MODEL_ID, usage=Usage(), answers=answers)


def _rank_resp(probabilities: list[float]) -> SystemOneResponse:
    return _resp(
        {f"candidate_{i}": NoulAnswer(type="noul", noul=p) for i, p in enumerate(probabilities)}
    )


def _facts_resp(choices: list[tuple[str, float]]) -> SystemOneResponse:
    return _resp(
        {
            f"fact_{i}": ChoiceAnswer(
                type="choice",
                choice=label,
                confidence=confidence,
                probabilities={"true": confidence, "false": 1.0 - confidence},
            )
            for i, (label, confidence) in enumerate(choices)
        }
    )


def _scores_resp(scores: list[tuple[float, float]]) -> SystemOneResponse:
    keys = ("A", "B", "C")
    return _resp(
        {
            f"variant_{keys[i]}": ScoreAnswer(
                type="score",
                score=score,
                confidence=confidence,
                legend={0: "0", 1: "1", 2: "2", 3: "3", 4: "4"},
                probabilities={0: 0.1, 1: 0.1, 2: 0.1, 3: 0.3, 4: 0.4},
            )
            for i, (score, confidence) in enumerate(scores)
        }
    )


class ScriptedTransport:
    """脚本化 fake transport：按脚本依次返回响应/抛异常（单项脚本恒定复用）；记录调用入参。"""

    def __init__(self, script: list[SystemOneResponse | Exception]) -> None:
        self._script = script
        self.calls: list[tuple[str, Mapping[str, Question], str]] = []

    async def system_one(
        self, state: str, questions: Mapping[str, Question], *, model: str
    ) -> SystemOneResponse:
        self.calls.append((state, questions, model))
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _shape(model: BaseModel) -> dict[str, str]:
    return {k: type(v).__name__ for k, v in model.model_dump().items()}


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


# ---------- 模型 ID 钉死（MUST-12 禁别名） ----------


def test_jev_model_id_constant() -> None:
    assert JEV_MODEL_ID == "jev-1.13.0"


def test_alias_config_rejected() -> None:
    with pytest.raises(ConfigurationError):
        JevDecider(_cfg(jev_model_id="jev-latest"))


# ---------- 三方法（mock transport） ----------


async def test_rank_components_orders_by_noul() -> None:
    transport = ScriptedTransport([_rank_resp([0.3, 0.9, 0.6])])
    cands = [*_cands(), Candidate(name="Card", path="c.tsx", line=1, score=0.5, source="symbol")]
    out = await JevDecider(_cfg(), transport).rank_components("改按钮", cands)
    assert out.order == [1, 2, 0]
    assert out.confidence == 0.9
    state, questions, model = transport.calls[0]
    assert model == JEV_MODEL_ID
    assert set(questions) == {"candidate_0", "candidate_1", "candidate_2"}
    assert "改按钮" in state


async def test_rank_empty_candidates_short_circuits() -> None:
    transport = ScriptedTransport([_rank_resp([])])
    out = await JevDecider(_cfg(), transport).rank_components("改按钮", [])
    assert out.order == []
    assert transport.calls == []


async def test_probe_facts_maps_choice_answers() -> None:
    transport = ScriptedTransport([_facts_resp([("true", 0.8), ("false", 0.7)])])
    out = await JevDecider(_cfg(), transport).probe_facts("改按钮", _facts())
    assert out.judgments[0].key == "target_file_exists"
    assert out.judgments[0].passed is True
    assert out.judgments[0].confidence == 0.8
    assert out.judgments[1].passed is False
    assert out.judgments[1].confidence == 0.7
    assert out.overall_confidence == pytest.approx(0.75)


async def test_score_prompts_rounds_expected_score() -> None:
    transport = ScriptedTransport([_scores_resp([(3.2, 0.7), (1.6, 0.6), (4.0, 0.9)])])
    variants = [("A", "保守版"), ("B", "标准版"), ("C", "激进版")]
    out = await JevDecider(_cfg(), transport).score_prompts("项目上下文", variants)
    assert [(s.variant, s.score, s.confidence) for s in out.scores] == [
        ("A", 3, 0.7),
        ("B", 2, 0.6),
        ("C", 4, 0.9),
    ]


# ---------- state 截断（F-202：30000 token 硬限 + state.truncated） ----------


async def test_state_over_limit_truncated(caplog: pytest.LogCaptureFixture) -> None:
    cfg = _cfg(max_state_tokens=10)
    transport = ScriptedTransport([_scores_resp([(3.0, 0.7), (2.0, 0.6), (1.0, 0.5)])])
    decider = JevDecider(cfg, transport)
    with caplog.at_level(logging.WARNING, logger="devprompt.decision"):
        out = await decider.score_prompts(
            "上下文" * 100, [("A", "正文" * 50), ("B", "b"), ("C", "c")]
        )
    assert len(out.scores) == 3  # 截断后输出仍合法
    state = transport.calls[0][0]
    assert len(state) <= 10
    assert _estimate_tokens(state) <= 10
    assert any(r.getMessage().startswith("state.truncated") for r in caplog.records)


async def test_state_within_limit_untouched() -> None:
    transport = ScriptedTransport([_rank_resp([0.9, 0.1])])
    await JevDecider(_cfg(), transport).rank_components("改按钮", _cands())
    assert transport.calls[0][0] == "改按钮"


# ---------- 429 手写指数退避（F-202：0.5 × 2^n，n ≤ 4） ----------


async def test_429_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    transport = ScriptedTransport([_RATE_LIMITED, _RATE_LIMITED, _rank_resp([0.9, 0.1])])
    out = await JevDecider(_cfg(), transport).rank_components("改按钮", _cands())
    assert out.order == [0, 1]
    assert sleeps == [0.5, 1.0]
    assert len(transport.calls) == 3


async def test_429_exhausted_raises_original(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    transport = ScriptedTransport([_RATE_LIMITED])
    with pytest.raises(TypeSafeRateLimitError):
        await JevDecider(_cfg(), transport).rank_components("改按钮", _cands())
    assert sleeps == [0.5, 1.0, 2.0, 4.0, 8.0]  # n = 0..4
    assert len(transport.calls) == 6  # 首发 + 5 次重试


# ---------- create_decider 双路径 + 连续失败切换（MUST-12） ----------


def test_create_decider_with_key_builds_failover() -> None:
    d = create_decider(_cfg())
    assert isinstance(d, FailoverDecider)
    assert isinstance(d._primary, JevDecider)  # noqa: SLF001


def test_create_decider_without_key_returns_llm() -> None:
    d = create_decider(AppConfig(_env_file=None))  # type: ignore[call-arg]
    assert isinstance(d, LLMFallbackDecider)


def test_create_decider_empty_key_returns_llm() -> None:
    d = create_decider(AppConfig(_env_file=None, typesafe_api_key=""))  # type: ignore[call-arg]
    assert isinstance(d, LLMFallbackDecider)


def test_create_decider_forced_fallback_ignores_key() -> None:
    d = create_decider(_cfg(decider="fallback"))
    assert isinstance(d, LLMFallbackDecider)


async def test_create_decider_explicit_jev_without_key_logs_switch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="devprompt.decision"):
        d = create_decider(AppConfig(_env_file=None, decider="jev"))  # type: ignore[call-arg]
    assert isinstance(d, LLMFallbackDecider)
    assert any(
        "decider.switched" in r.getMessage() and "jev-no-api-key" in r.getMessage()
        for r in caplog.records
    )


class _ExplodingPrimary:
    """恒抛 primary：验证 FailoverDecider 失败计数与切换。"""

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        raise GenerationError("jev down", code=5001)

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        raise GenerationError("jev down", code=5001)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        raise GenerationError("jev down", code=5001)


async def test_failover_switches_after_three_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=[1, 0], confidence=0.5)

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    d = FailoverDecider(_ExplodingPrimary(), _cfg())
    with caplog.at_level(logging.WARNING, logger="devprompt.decision"):
        for _ in range(3):
            with pytest.raises(GenerationError):
                await d.rank_components("改按钮", _cands())
        out = await d.rank_components("改按钮", _cands())
    assert out.order == [1, 0]  # 第 4 次调用由 LLM 版接管
    assert any(
        "decider.switched" in r.getMessage() and "jev-consecutive-failures" in r.getMessage()
        for r in caplog.records
    )


async def test_failover_resets_count_on_success() -> None:
    # 用非 429 异常：JevDecider 的 _ask 只对 429 内部重试，其余异常直接冒泡到 FailoverDecider
    down = GenerationError("jev down", code=5001)
    responses: list[SystemOneResponse | Exception] = [
        down,
        _rank_resp([0.9, 0.1]),
        down,
        down,
        _rank_resp([0.2, 0.8]),
    ]
    transport = ScriptedTransport(responses)
    d = FailoverDecider(JevDecider(_cfg(), transport), _cfg(), max_failures=3)
    with pytest.raises(GenerationError):
        await d.rank_components("改按钮", _cands())
    first = await d.rank_components("改按钮", _cands())  # 成功清零
    with pytest.raises(GenerationError):
        await d.rank_components("改按钮", _cands())
    with pytest.raises(GenerationError):
        await d.rank_components("改按钮", _cands())
    second = await d.rank_components("改按钮", _cands())  # 未达 3 次连续失败，仍在 Jev 路径
    assert (first.order, second.order) == ([0, 1], [1, 0])
    assert d._delegate is None  # noqa: SLF001


# ---------- 契约一致性（MUST-12：Jev 与 fallback 输出结构逐字段一致） ----------


async def test_rank_output_shape_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=[1, 0], confidence=0.9)

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    llm_out = await LLMFallbackDecider(_cfg()).rank_components("改按钮", _cands())
    jev_out = await JevDecider(_cfg(), ScriptedTransport([_rank_resp([0.2, 0.9])])).rank_components(
        "改按钮", _cands()
    )
    assert set(jev_out.model_dump()) == set(llm_out.model_dump())
    assert _shape(jev_out) == _shape(llm_out)
    assert (jev_out.order, jev_out.confidence) == (llm_out.order, llm_out.confidence)


async def test_probe_output_shape_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[FactProbeOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> FactProbeOutput:
        return FactProbeOutput(
            judgments=[FactJudgment(key="target_file_exists", passed=True, confidence=0.8)],
            overall_confidence=0.8,
        )

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    llm_out = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", _facts())
    jev_out = await JevDecider(
        _cfg(), ScriptedTransport([_facts_resp([("true", 0.8), ("false", 0.9)])])
    ).probe_facts("改按钮", _facts())
    assert set(jev_out.model_dump()) == set(llm_out.model_dump())
    assert _shape(jev_out) == _shape(llm_out)


async def test_score_output_shape_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[ScorePromptsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> ScorePromptsOutput:
        return ScorePromptsOutput(scores=[VariantScore(variant="A", score=3, confidence=0.7)])

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    variants = [("A", "保守版")]
    llm_out = await LLMFallbackDecider(_cfg()).score_prompts("ctx", variants)
    jev_out = await JevDecider(
        _cfg(), ScriptedTransport([_scores_resp([(3.2, 0.7), (2.0, 0.6), (1.0, 0.5)])])
    ).score_prompts("ctx", variants)
    assert set(jev_out.model_dump()) == set(llm_out.model_dump())
    assert _shape(jev_out) == _shape(llm_out)
