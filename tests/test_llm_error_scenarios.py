"""LLM 失败场景注入测试（M-9）。

补上此前完全缺失的覆盖：339 个测试中没有任何 LLM 失败场景，MUST-13 的超时路径与
错误码分支从未被验证过。本文件用 monkeypatch 替换底层调用，注入 6 种失败。

覆盖的错误码（用户 2026-10-16 裁定，5 个细分码 + 1 个回退）：
    timeout → 5011 · rate_limit → 5012 · insufficient_quota → 5013
    invalid_api_key → 5014 · upstream_error(500/网络) → 5015 · 未识别 → 4002
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.harness.llm import chat_structured, classify_llm_failure

_API_KEY = "sk-test-key-that-must-not-leak"


class _Probe(BaseModel):
    """最小合法输出类型（须为 BaseModel 子类以满足 chat_structured 的 ModelT 约束）。"""

    verdict: str


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        llm_base_url="https://api.example.com/v1",
        llm_api_key=_API_KEY,
        llm_model="test-model",
        _env_file=None,  # type: ignore[call-arg]
    )


def _boom(exc: BaseException) -> Any:
    """构造一个「调用即抛」的 Runner.run 替身。"""

    async def _run(*_a: object, **_k: object) -> None:
        raise exc

    return _run


#: 场景 → (异常样例, 期望错误码, 期望 context.scenario)
CASES: tuple[tuple[str, BaseException, int, str], ...] = (
    ("timeout", TimeoutError("timed out"), 5011, "timeout"),
    ("rate_limit", RuntimeError("Rate limit exceeded for model"), 5012, "rate_limit"),
    ("insufficient_quota", RuntimeError("Insufficient balance"), 5013, "insufficient_quota"),
    ("invalid_api_key", RuntimeError("Invalid API key provided"), 5014, "invalid_api_key"),
    ("server_error_500", RuntimeError("500 Internal Server Error"), 5015, "upstream_error"),
    (
        "network",
        RuntimeError("Connection error to https://api.example.com"),
        5015,
        "upstream_error",
    ),
    ("unclassified", RuntimeError("something odd happened"), 4002, "unclassified"),
)


class TestClassify:
    def test_timeout_detected_by_type(self) -> None:
        assert classify_llm_failure(TimeoutError("x")) == ("timeout", 5011)

    def test_asyncio_timeout_detected_by_type(self) -> None:
        assert classify_llm_failure(asyncio.TimeoutError()) == ("timeout", 5011)

    def test_quota_wins_over_rate_limit(self) -> None:
        """「余额不足」常与 429 同时出现，额度判断须优先。"""
        exc = RuntimeError("429 rate limit, insufficient balance")
        assert classify_llm_failure(exc) == ("insufficient_quota", 5013)

    def test_unknown_returns_none(self) -> None:
        assert classify_llm_failure(RuntimeError("odd")) is None


class TestChatStructuredFailures:
    @pytest.mark.parametrize(("name", "exc", "code", "scenario"), CASES, ids=[c[0] for c in CASES])
    async def test_maps_to_specific_code(
        self,
        cfg: AppConfig,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        exc: BaseException,
        code: int,
        scenario: str,
    ) -> None:
        monkeypatch.setattr("devprompt_ai.harness.llm._ensure_client", lambda _c: None)
        monkeypatch.setattr("devprompt_ai.harness.llm.Runner.run", staticmethod(_boom(exc)))

        with pytest.raises(GenerationError) as info:
            await chat_structured(cfg, _Probe, "sys", "user")
        assert info.value.code == code, name
        assert info.value.context["scenario"] == scenario, name

    async def test_context_carries_model_and_type(
        self, cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("devprompt_ai.harness.llm._ensure_client", lambda _c: None)
        monkeypatch.setattr(
            "devprompt_ai.harness.llm.Runner.run", staticmethod(_boom(TimeoutError("t")))
        )

        with pytest.raises(GenerationError) as info:
            await chat_structured(cfg, _Probe, "sys", "user")
        assert info.value.context["model"] == "test-model"
        assert info.value.context["output_type"] == "_Probe"

    async def test_message_never_leaks_api_key(
        self, cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MUST-19：异常 message 不得回显密钥，也不得回显原始异常文本。"""
        monkeypatch.setattr("devprompt_ai.harness.llm._ensure_client", lambda _c: None)
        monkeypatch.setattr(
            "devprompt_ai.harness.llm.Runner.run",
            staticmethod(_boom(RuntimeError(f"boom with {_API_KEY} inside"))),
        )

        with pytest.raises(GenerationError) as info:
            await chat_structured(cfg, _Probe, "sys", "user")
        assert _API_KEY not in str(info.value)

    async def test_original_exception_is_cause(
        self, cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """保留 __cause__ 便于排障，同时不把原文塞进 message。"""
        original = TimeoutError("original detail")
        monkeypatch.setattr("devprompt_ai.harness.llm._ensure_client", lambda _c: None)
        monkeypatch.setattr("devprompt_ai.harness.llm.Runner.run", staticmethod(_boom(original)))

        with pytest.raises(GenerationError) as info:
            await chat_structured(cfg, _Probe, "sys", "user")
        assert info.value.__cause__ is original

    async def test_retry_failure_also_mapped(
        self, cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """纠偏重试阶段的失败同样须映射，不能漏出裸异常。"""

        class _BadResult:
            usage = None
            final_output = "not json at all"

        calls = {"n": 0}

        async def _run(*_a: object, **_k: object) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                return _BadResult()
            raise RuntimeError("Invalid API key")

        monkeypatch.setattr("devprompt_ai.harness.llm._ensure_client", lambda _c: None)
        monkeypatch.setattr("devprompt_ai.harness.llm.Runner.run", staticmethod(_run))

        with pytest.raises(GenerationError) as info:
            await chat_structured(cfg, _Probe, "sys", "user")
        assert info.value.code == 5014
        assert calls["n"] == 2
