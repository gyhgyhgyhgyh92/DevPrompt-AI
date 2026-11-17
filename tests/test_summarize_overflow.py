"""A8/B11 测试：超窗一次重发、LLM 摘要与确定性兜底。"""

from __future__ import annotations

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.context.budget import RequestBudgetError
from devprompt_ai.harness import summarize as summarize_module
from devprompt_ai.harness.overflow import is_context_overflow, with_overflow_retry
from devprompt_ai.harness.summarize import SummaryOutput, summarize_history


def test_overflow_classification() -> None:
    assert is_context_overflow(RequestBudgetError("x"))
    assert is_context_overflow(RuntimeError("maximum context length exceeded"))
    assert is_context_overflow(ValueError("prompt is too long: 200k tokens"))
    assert is_context_overflow(RuntimeError("rate limit")) is False


async def test_overflow_compacts_once_and_retries() -> None:
    calls = {"n": 0, "compacted": 0}

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("context length exceeded")
        return "ok"

    async def compact() -> None:
        calls["compacted"] += 1

    assert await with_overflow_retry(call, compact=compact) == "ok"
    assert calls == {"n": 2, "compacted": 1}


async def test_non_overflow_is_not_retried() -> None:
    calls = {"n": 0, "compacted": 0}

    async def call() -> str:
        calls["n"] += 1
        raise RuntimeError("rate limit")

    async def compact() -> None:
        calls["compacted"] += 1

    with pytest.raises(RuntimeError):
        await with_overflow_retry(call, compact=compact)
    assert calls == {"n": 1, "compacted": 0}


async def test_second_overflow_failure_propagates() -> None:
    calls = {"n": 0}

    async def call() -> str:
        calls["n"] += 1
        raise RequestBudgetError("still too big")

    async def compact() -> None:
        return None

    with pytest.raises(RequestBudgetError):
        await with_overflow_retry(call, compact=compact)
    assert calls["n"] == 2, "只重试一次，不无限循环"


async def test_summarize_returns_llm_summary_when_covered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*_args: object, **_kwargs: object) -> SummaryOutput:
        return SummaryOutput(summary="决定加导出，涉及 src/ui/Button.tsx")

    monkeypatch.setattr(summarize_module, "chat_structured", fake_chat)

    text, used_fallback = await summarize_history(
        AppConfig(),
        "history",
        required_terms=["导出"],
    )

    assert used_fallback is False
    assert "导出" in text


async def test_summarize_falls_back_when_term_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(*_args: object, **_kwargs: object) -> SummaryOutput:
        return SummaryOutput(summary="随便说说")

    monkeypatch.setattr(summarize_module, "chat_structured", fake_chat)

    text, used_fallback = await summarize_history(
        AppConfig(),
        "history",
        required_terms=["导出"],
        fallback_context={"objective": "加导出按钮", "current": "已定位"},
    )

    assert used_fallback is True
    assert "加导出按钮" in text
    assert "当前进度" in text


async def test_summarize_falls_back_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_args: object, **_kwargs: object) -> SummaryOutput:
        raise RuntimeError("llm down")

    monkeypatch.setattr(summarize_module, "chat_structured", boom)

    text, used_fallback = await summarize_history(
        AppConfig(), "history", fallback_context={"objective": "目标"}
    )

    assert used_fallback is True
    assert "目标" in text
