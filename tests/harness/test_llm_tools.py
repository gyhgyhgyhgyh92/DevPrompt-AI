"""chat_with_tools：拦截 function_call、无调用取文本、超时映射（2026-10-22）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.harness import llm


class FakeModel:
    def __init__(self, output: list[Any], *, delay: float = 0.0) -> None:
        self.output = output
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def get_response(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(output=self.output, usage=None)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeModel) -> FakeModel:
    monkeypatch.setattr(llm, "build_model", lambda _cfg: fake)
    return fake


def _cfg() -> AppConfig:
    return AppConfig(_env_file=None)  # type: ignore[call-arg]


async def test_returns_tool_call_from_sdk_object(monkeypatch: pytest.MonkeyPatch) -> None:
    call = SimpleNamespace(
        type="function_call", name="AskUserQuestion", arguments='{"questions": []}', call_id="c1"
    )
    _patch(monkeypatch, FakeModel([call]))

    result = await llm.chat_with_tools(_cfg(), "system", "user")

    assert result.tool_call is not None
    assert result.tool_call.name == "AskUserQuestion"
    assert result.tool_call.call_id == "c1"
    assert result.tool_call.arguments == '{"questions": []}'
    assert result.text == ""


async def test_returns_tool_call_from_native_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """anthropic/gemini 原生适配器返回普通 dict，同样要能识别。"""
    fake = _patch(
        monkeypatch,
        FakeModel(
            [
                {
                    "type": "function_call",
                    "name": "AskUserQuestion",
                    "arguments": "{}",
                    "call_id": "c2",
                }
            ]
        ),
    )

    result = await llm.chat_with_tools(_cfg(), "system", "user")

    assert result.tool_call is not None and result.tool_call.call_id == "c2"
    assert fake.calls[0]["tools"], "必须把 AskUserQuestion 传给模型"


async def test_no_tool_call_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeModel([]))

    result = await llm.chat_with_tools(_cfg(), "system", "user")

    assert result.tool_call is None
    assert result.text == ""


async def test_timeout_maps_to_business_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeModel([], delay=1.0))

    with pytest.raises(DevPromptError) as caught:
        await llm.chat_with_tools(_cfg(), "system", "user", timeout=0.01)

    assert 5011 <= caught.value.code <= 5015


async def test_invokes_model_once_with_ask_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch(monkeypatch, FakeModel([]))

    await llm.chat_with_tools(_cfg(), "system", "user")

    assert len(fake.calls) == 1
    tools = fake.calls[0]["tools"]
    assert [tool.name for tool in tools] == ["AskUserQuestion"]
    assert fake.calls[0]["output_schema"] is None
    assert fake.calls[0]["handoffs"] == []
