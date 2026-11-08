"""token 估算测试：分字符口径、边界与「必计 reasoning」的防回归。"""

from __future__ import annotations

from devprompt_ai.domain.context.tokens import estimate_message_tokens, estimate_tokens


def test_empty_text_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_ascii_is_four_chars_per_token_rounded_up() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2, "向上取整，宁可高估"


def test_cjk_is_more_expensive_than_ascii() -> None:
    assert estimate_tokens("中") == 1
    assert estimate_tokens("中" * 6) == 5
    assert estimate_tokens("中" * 6) > estimate_tokens("a" * 6)


def test_mixed_text_sums_both_parts() -> None:
    # 4 ASCII = 1 token；6 CJK = 5 token
    assert estimate_tokens("abcd" + "中" * 6) == 6


def test_message_counts_tool_calls_and_reasoning() -> None:
    base = estimate_message_tokens("abcd")
    with_extras = estimate_message_tokens(
        "abcd", tool_calls_json='{"name":"x"}', reasoning="先看事实再决定"
    )

    assert base == 1
    assert with_extras > base, "漏算 reasoning/tool_calls 会让压缩偏晚"
