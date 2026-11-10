"""LLM 用量记录测试（2026-11-10）：dict/对象两种形态、total 兜底与负数钳制。"""

from __future__ import annotations

from types import SimpleNamespace

from devprompt_ai.common.cost import take_llm_usage
from devprompt_ai.harness.llm import _record_usage, last_usage


def test_dict_usage_total_is_read() -> None:
    take_llm_usage()  # 清空
    _record_usage(
        {
            "total_tokens": 30,
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "cached_tokens": 5,
        }
    )

    assert last_usage() == {
        "total_tokens": 30,
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "cached_tokens": 5,
    }
    usage = take_llm_usage()
    assert (usage.total, usage.prompt, usage.completion, usage.cached) == (30, 20, 10, 5)


def test_missing_total_falls_back_to_prompt_plus_completion() -> None:
    take_llm_usage()
    _record_usage({"prompt_tokens": 12, "completion_tokens": 8})

    assert last_usage() is not None
    assert last_usage()["total_tokens"] == 20
    assert take_llm_usage().total == 20


def test_object_usage_is_supported() -> None:
    take_llm_usage()
    _record_usage(SimpleNamespace(total_tokens=7, prompt_tokens=4, completion_tokens=3))

    assert last_usage() is not None
    assert last_usage()["total_tokens"] == 7


def test_agents_usage_input_output_aliases() -> None:
    """原生适配器返回 agents.usage.Usage：input/output 必须映射到 prompt/completion。"""
    from agents.usage import Usage as AgentsUsage

    take_llm_usage()
    _record_usage(AgentsUsage(input_tokens=4, output_tokens=3, total_tokens=7))

    assert last_usage() == {
        "total_tokens": 7,
        "prompt_tokens": 4,
        "completion_tokens": 3,
        "cached_tokens": 0,
    }


def test_negative_usage_is_clamped() -> None:
    take_llm_usage()
    _record_usage({"total_tokens": -10, "prompt_tokens": -3, "completion_tokens": -2})

    usage = take_llm_usage()
    assert (usage.total, usage.prompt, usage.completion) == (0, 0, 0)
