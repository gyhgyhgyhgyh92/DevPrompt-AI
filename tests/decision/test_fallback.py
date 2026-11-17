"""LLMFallbackDecider 行为测试：用 monkeypatch 替换 chat_structured，无真实网络。"""

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import fallback as fb
from devprompt_ai.decision.fallback import LLMFallbackDecider
from devprompt_ai.domain.decision.port import (
    FactProbeOutput,
    NextActionOutput,
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
        **_kwargs: object,
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
        **_kwargs: object,
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
        **_kwargs: object,
    ) -> FactProbeOutput:
        return sentinel

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    facts = [FactResult(key="target_file_exists", passed=True, evidence="file=x")]
    out = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", facts)
    assert out is sentinel  # 输出结构直接透传（结构统一，MUST-12）


async def test_rank_truncates_state_over_limit_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """MUST-09 / F-805：state 超限 → 截断（非报错）且记 state.truncated 日志。"""
    import logging as _logging

    from devprompt_ai.common.text import estimate_tokens

    captured: dict[str, str] = {}

    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
        **_kwargs: object,
    ) -> RankComponentsOutput:
        captured["user"] = user
        return RankComponentsOutput(order=[1, 0], confidence=0.8)

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    cfg = AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="https://fake/v1",
        llm_model="fake-model",
        max_state_tokens=10,
        max_context_length=100,
    )
    big = "候选名称" * 50
    cands = [
        Candidate(name=big, path=big, line=1, score=1.0, source="symbol"),
        Candidate(name=big + "二", path=big, line=2, score=1.0, source="symbol"),
    ]
    with caplog.at_level(_logging.INFO, logger="devprompt.events"):
        await LLMFallbackDecider(cfg).rank_components("改按钮", cands)

    assert estimate_tokens(captured["user"]) <= 10  # 截断到 ≤ max_state_tokens
    trunc = next(r for r in caplog.records if r.getMessage() == "state.truncated")
    assert getattr(trunc, "reason", None) == "state-over-limit"
    assert getattr(trunc, "limit", None) == 10


async def test_rank_state_passthrough_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """未超限时 state 原样透传（MUST-09：不超限不改动 state）。"""
    from devprompt_ai.decision.prompts import RANK_USER, rank_evidence

    captured: dict[str, str] = {}

    async def fake_llm(
        cfg: AppConfig,
        output_type: type[RankComponentsOutput],
        system: str,
        user: str,
        *,
        timeout: float = 10.0,
        **_kwargs: object,
    ) -> RankComponentsOutput:
        captured["user"] = user
        return RankComponentsOutput(order=[1, 0], confidence=0.8)

    monkeypatch.setattr(fb, "chat_structured", fake_llm)
    cands = _cands()
    await LLMFallbackDecider(_cfg()).rank_components("改按钮", cands)

    listing = "\n".join(f"{i}. {c.name}  ({c.path})" for i, c in enumerate(cands))
    assert captured["user"] == RANK_USER.format(evidence=rank_evidence("改按钮", listing))


def test_next_action_accepts_delegation_orders() -> None:
    """K6 多波来源：决策输出可携带只读工单草案；写工 profile 在解析层被拒（K4 边界）。"""
    out = NextActionOutput(
        action="delegate",
        confidence_source="no_data",
        delegation_orders=[
            {"profile": "verifier", "objective": "审查改动", "scope_files": ["src/a.py"]},
            {"objective": "默认探查档"},  # profile 缺省 → code_scout
        ],
    )

    assert out.delegation_orders[0].profile == "verifier"
    assert out.delegation_orders[1].profile == "code_scout"

    import pytest as _pytest
    from pydantic import ValidationError as _ValidationError

    with _pytest.raises(_ValidationError):
        NextActionOutput(
            action="delegate",
            confidence_source="no_data",
            delegation_orders=[{"profile": "patcher", "objective": "写工不下发"}],
        )
