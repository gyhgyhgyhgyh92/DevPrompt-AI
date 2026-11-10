"""模型参数接线的回归测试（2026-11-10）。

覆盖两个曾经断开的环节：
1. `_candidate_cfg` 必须按**候选条目**取 effort / 窗口，不能继承激活条目；
2. `_tools_once`（AskUserQuestion 探针路径）必须把 effort 带进 `ModelSettings.extra_body`。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.harness import llm


def _cfg(**kwargs: Any) -> AppConfig:
    return AppConfig(_env_file=None, **kwargs)  # type: ignore[call-arg]


class TestCandidateConfig:
    def test_candidate_uses_its_own_effort_and_window(self) -> None:
        active = _cfg(
            llm_provider="deepseek",
            llm_model="deepseek-flash",
            llm_params={"reasoning_effort": "high", "temperature": 0.3},
            max_context_length=1_000_000,
        )
        entry = {
            "provider": "deepseek",
            "model_id": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "k",
            "api_mode": "chat_completions",
            "reasoning_effort": "low",
            "max_context_length": 262_144,
        }
        candidate = llm._candidate_cfg(active, entry)
        assert candidate.llm_params == {"temperature": 0.3, "reasoning_effort": "low"}
        assert candidate.max_context_length == 262_144

    def test_empty_effort_resolves_none_for_deepseek(self) -> None:
        active = _cfg(
            llm_provider="deepseek",
            llm_model="deepseek-flash",
            llm_params={"reasoning_effort": "high"},
        )
        entry = {
            "provider": "deepseek",
            "model_id": "deepseek-flash",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "k",
            "api_mode": "chat_completions",
            "reasoning_effort": "",
        }
        candidate = llm._candidate_cfg(active, entry)
        assert candidate.llm_params["reasoning_effort"] == "none"

    def test_empty_effort_is_removed_for_model_without_none(self) -> None:
        active = _cfg(
            llm_provider="openai",
            llm_model="gpt-x",
            llm_params={"reasoning_effort": "high"},
        )
        entry = {
            "provider": "openai",
            "model_id": "gpt-x",
            "base_url": "https://api.openai.com/v1",
            "api_key": "k",
            "api_mode": "responses",
            "reasoning_effort": "",
        }
        candidate = llm._candidate_cfg(active, entry)
        assert "reasoning_effort" not in candidate.llm_params

    def test_missing_window_falls_back_to_static_nominal(self) -> None:
        """条目未选档时不能用全局 1M：必须回落该模型的标称窗口。"""
        active = _cfg(llm_provider="deepseek", llm_model="deepseek-flash")
        entry = {
            "provider": "deepseek",
            "model_id": "deepseek-flash",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "k",
            "api_mode": "chat_completions",
        }
        candidate = llm._candidate_cfg(active, entry)
        assert candidate.runtime_window() == 1_048_576


class TestToolsOnceSettings:
    @pytest.mark.asyncio
    async def test_probe_path_carries_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        class _FakeModel:
            async def get_response(self, **kwargs: Any) -> Any:
                captured.update(kwargs)
                return SimpleNamespace(output=[], usage=None)

        async def _no_stat(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(llm, "build_model", lambda _cfg: _FakeModel())
        monkeypatch.setattr(llm, "_record_routing_stat", _no_stat)

        cfg = _cfg(
            llm_provider="deepseek",
            llm_model="deepseek-flash",
            api_mode="chat_completions",
            llm_params={"reasoning_effort": "high"},
            max_context_length=128_000,
        )
        await llm._tools_once(cfg, "sys", "user", timeout=5, purpose="probe")

        settings = captured["model_settings"]
        assert settings.extra_body == {"reasoning_effort": "high"}
        assert settings.tool_choice == "auto"
