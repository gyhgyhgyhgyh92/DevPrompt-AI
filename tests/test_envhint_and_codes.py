"""环境提示与集中错误码表测试（N-8 + Batch 1 前置）。

关注两件事：
1. 提示**可操作**（说明缺什么、去哪填）且**不回显任何值**（MUST-19）
2. 错误码表是权威清单——异常类默认码必须已登记（否则 M-10 的前端映射校验会漏）
"""

from __future__ import annotations

import pytest

from devprompt_ai.common.envhint import render_env_hint
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.error_codes import (
    ALL_ERROR_CODES,
    ERROR_CODES,
    LLM_FAILURE_CODES,
    registered,
)
from devprompt_ai.domain.errors import ConfigurationError, GenerationError


class TestRenderEnvHint:
    def test_lists_every_problem(self) -> None:
        text = render_env_hint([("LLM_API_KEY", "缺密钥"), ("LLM_MODEL", "缺模型")])
        assert "LLM_API_KEY" in text
        assert "LLM_MODEL" in text
        assert "缺密钥" in text and "缺模型" in text

    def test_includes_fix_location(self) -> None:
        assert ".env" in render_env_hint([("X", "y")])

    def test_empty_input_returns_empty_string(self) -> None:
        assert render_env_hint([]) == ""

    def test_states_total_count(self) -> None:
        """一次性列出全部问题（N-8 核心：不让用户逐个试错）。"""
        text = render_env_hint([("A", "x"), ("B", "y"), ("C", "z")])
        assert "3" in text


class TestLlmProblems:
    def test_default_config_lists_three(self) -> None:
        cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
        names = [name for name, _ in cfg.llm_problems()]
        assert names == ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]

    def test_complete_config_lists_none(self) -> None:
        cfg = AppConfig(
            llm_base_url="https://api.example.com/v1",
            llm_api_key="k",
            llm_model="m",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert cfg.llm_problems() == []

    def test_validate_does_not_block_on_missing_llm(self) -> None:
        """本地工具允许先启动再配模型（用户 2026-10-16 裁定，恢复 F-003 契约）。"""
        AppConfig(_env_file=None).validate()  # type: ignore[call-arg]  # 不抛即过


class TestErrorCodeTable:
    def test_all_codes_sorted_and_unique(self) -> None:
        assert list(ALL_ERROR_CODES) == sorted(set(ALL_ERROR_CODES))

    def test_exception_defaults_are_registered(self) -> None:
        """异常类默认码必须在码表内——否则前端映射表（M-10）会漏。"""
        from devprompt_ai.domain.errors import (
            DecisionError,
            DevPromptError,
            RetrievalError,
            StateError,
        )

        for exc_type in (
            DevPromptError,
            RetrievalError,
            DecisionError,
            GenerationError,
            StateError,
            ConfigurationError,
        ):
            assert exc_type("x").code in ERROR_CODES, f"{exc_type.__name__} 默认码未登记"

    def test_registered_rejects_unknown_code(self) -> None:
        with pytest.raises(KeyError, match="未在"):
            registered(9999)

    def test_registered_passes_through_known(self) -> None:
        assert registered(9002) == 9002

    def test_llm_failure_codes_are_five(self) -> None:
        """用户 2026-10-16 裁定：LLM 失败细分 5 个码（5011~5015）。"""
        assert sorted(LLM_FAILURE_CODES) == [5011, 5012, 5013, 5014, 5015]

    def test_llm_failures_separate_from_decision_rate_limit(self) -> None:
        """3004（决策阶段限流）与 5012（生成阶段限流）语义相近但不可合并（用户裁定）。"""
        assert ERROR_CODES[3004] != ERROR_CODES[5012]
        assert "决策阶段" in ERROR_CODES[3004]
        assert "生成阶段" in ERROR_CODES[5012]

    def test_every_code_has_meaning(self) -> None:
        for code, meaning in ERROR_CODES.items():
            assert meaning.strip(), f"{code} 缺少语义说明"
