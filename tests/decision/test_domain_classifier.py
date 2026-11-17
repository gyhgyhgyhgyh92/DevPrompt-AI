"""领域分类 LLM 实现测试：合法分类、非法领域回退、调用失败回退、超长截断。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import domains as domain_mod
from devprompt_ai.decision.domains import FALLBACK_CONFIDENCE, DomainClassifier


def _cfg() -> AppConfig:
    return AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="https://fake/v1",
        llm_model="fake-model",
    )


def _patch_output(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[str]:
    """替换 chat_structured，记录收到的 user prompt 并返回固定输出。"""
    calls: list[str] = []

    async def fake_chat(cfg: AppConfig, out_type: Any, system: str, user: str, **kw: Any) -> Any:
        calls.append(user)
        return domain_mod.DomainClassifyOutput.model_validate(payload)

    monkeypatch.setattr(domain_mod, "chat_structured", fake_chat)
    return calls


async def test_classify_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_output(monkeypatch, {"domain": "creative", "confidence": 0.8})
    verdict = await DomainClassifier(_cfg()).classify("写一首诗")
    assert verdict.domain == "creative"
    assert verdict.source == "llm"
    assert verdict.confidence == 0.8


async def test_classify_invalid_domain_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_output(monkeypatch, {"domain": "unknown_xyz", "confidence": 0.9})
    verdict = await DomainClassifier(_cfg()).classify("算个账")
    assert verdict.domain == "work"
    assert verdict.source == "fallback"
    assert verdict.confidence == FALLBACK_CONFIDENCE


async def test_classify_low_confidence_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """MUST-11d：LLM 自评低置信（<0.5）不得当实测判定，回退兜底包。"""
    _patch_output(monkeypatch, {"domain": "life", "confidence": 0.15})
    verdict = await DomainClassifier(_cfg()).classify("帮我弄一下那个事")
    assert verdict.domain == "work"
    assert verdict.source == "fallback"
    assert verdict.confidence == FALLBACK_CONFIDENCE


async def test_classify_llm_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("timeout")

    monkeypatch.setattr(domain_mod, "chat_structured", boom)
    verdict = await DomainClassifier(_cfg()).classify("随便看看")
    assert verdict.source == "fallback"
    assert verdict.domain == "work"


async def test_classify_truncates_long_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_output(monkeypatch, {"domain": "work", "confidence": 0.5})
    await DomainClassifier(_cfg()).classify("周报" * 3000)
    # 截断上限 2000 + user 模板固定段（14 域枚举）；断言长输入确实被截断而非全文上送
    assert calls and len(calls[0]) < 2000 + len(domain_mod._DOMAIN_USER)
