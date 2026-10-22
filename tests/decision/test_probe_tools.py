"""probe_facts 走 AskUserQuestion 工具调用（2026-10-22）。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import fallback
from devprompt_ai.decision.fallback import LLMFallbackDecider
from devprompt_ai.domain.decision.port import FactProbeOutput
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.harness.llm import ToolCallRequest, ToolChatResult


def _cfg() -> AppConfig:
    return AppConfig(_env_file=None)  # type: ignore[call-arg]


def _ask_payload() -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "question": "改动范围?",
                    "header": "范围",
                    "options": [
                        {"label": "只改一处", "description": "影响面最小"},
                        {"label": "整页调整", "description": "一致性更好"},
                    ],
                    "multiSelect": False,
                }
            ]
        }
    )


async def test_tool_call_becomes_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_tools(*_a: Any, **_k: Any) -> ToolChatResult:
        return ToolChatResult(
            tool_call=ToolCallRequest(
                call_id="call-1", name="AskUserQuestion", arguments=_ask_payload()
            )
        )

    monkeypatch.setattr(fallback, "chat_with_tools", fake_tools)
    result = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", [])

    assert [q.question for q in result.questions] == ["改动范围?"]
    assert result.questions[0].options[0].label == "只改一处"
    assert result.ask_call_id == "call-1"
    assert result.overall_confidence == 0.0  # 工具调用那一轮没有 judgments


async def test_invalid_arguments_become_no_question(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_tools(*_a: Any, **_k: Any) -> ToolChatResult:
        return ToolChatResult(
            tool_call=ToolCallRequest(call_id="c", name="AskUserQuestion", arguments="{bad")
        )

    monkeypatch.setattr(fallback, "chat_with_tools", fake_tools)
    result = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", [])

    assert result.questions == []
    assert result.ask_call_id == "c"


async def test_plain_text_is_parsed_as_judgments(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(
        {
            "judgments": [{"key": "token_defined", "passed": True, "confidence": 0.9}],
            "overall_confidence": 0.9,
            "task_kind": "execution",
            "questions": [],
        }
    )

    async def fake_tools(*_a: Any, **_k: Any) -> ToolChatResult:
        return ToolChatResult(text=body)

    monkeypatch.setattr(fallback, "chat_with_tools", fake_tools)
    result = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", [])

    assert result.overall_confidence == 0.9
    assert result.questions == []


async def test_tools_failure_degrades_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider 不支持 tools 时不 500：回落结构化调用，本轮不提问。"""
    calls: dict[str, bool] = {}

    async def boom(*_a: Any, **_k: Any) -> ToolChatResult:
        raise DevPromptError("tools unsupported", code=5011)

    async def fake_structured(*_a: Any, **_k: Any) -> Any:
        calls["structured"] = True
        return FactProbeOutput(judgments=[], overall_confidence=0.0)

    monkeypatch.setattr(fallback, "chat_with_tools", boom)
    monkeypatch.setattr(fallback, "chat_structured", fake_structured)

    result = await LLMFallbackDecider(_cfg()).probe_facts("改按钮", [])

    assert calls.get("structured") is True
    assert result.questions == []
