"""LLMFallbackDecider 行为测试：用 monkeypatch 替换 chat_structured，无真实网络。"""

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import fallback as fb
from devprompt_ai.decision.fallback import LLMFallbackDecider
from devprompt_ai.domain.decision.port import (
    FactProbeOutput,
    RankComponentsOutput,
)
from devprompt_ai.domain.errors import ConfigurationError, GenerationError
from devprompt_ai.domain.models import Candidate, FactResult


def _cfg() -> AppConfig:
    return AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="https://fake/v1",
        llm_model="fake-model",
    )


def _cands() -> list[Candidate]:
    return [
        Candidate(name="A", path="a.ts", line=1, score=2.0, source="symbol"),
        Candidate(name="B", path="b.ts", line=1, score=1.0, source="symbol"),
    ]


async def test_rank_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=[1, 0], confidence=0.8)

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    out = await LLMFallbackDecider(_cfg()).rank_components("改按钮", _cands())
    assert out.order == [1, 0]


async def test_rank_count_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=[0], confidence=0.8)  # 少排一个

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    with pytest.raises(GenerationError):
        await LLMFallbackDecider(_cfg()).rank_components("改按钮", _cands())


async def test_unconfigured_llm_raises_config_error() -> None:
    decider = LLMFallbackDecider(AppConfig(_env_file=None))  # type: ignore[call-arg]
    with pytest.raises(ConfigurationError):
        await decider.rank_components("改按钮", _cands())


async def test_probe_facts_passthrough_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = FactProbeOutput(judgments=[], overall_confidence=0.5)

    async def fake_llm(
        cfg: AppConfig,
        output_type: type[FactProbeOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
    ) -> FactProbeOutput:
        return sentinel

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    facts = [FactResult(key="target_file_exists", passed=True, evidence="file=x")]
    out = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", facts)
    assert out is sentinel  # 输出结构直接透传（结构统一，MUST-12）
