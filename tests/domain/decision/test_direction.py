"""方向分歧检测（2026-11-07 从 service.py 抽出）：只决定「是否重新给三套」。"""

from __future__ import annotations

import pytest

from devprompt_ai.domain.decision.direction import detect_direction_conflict


@pytest.mark.parametrize(
    "sentence",
    [
        "推翻刚才那套",
        "还是别按上一版改了",
        "换个方向，先保证可回滚",
        "换个思路重来",
        "这次走激进一点",
        "保守一点，别动测试",
        "不是这个思路，我要的是断流可恢复",
        "  重新考虑　一下  ",
    ],
)
def test_conflict_sentences_hit(sentence: str) -> None:
    assert detect_direction_conflict(sentence) is True


@pytest.mark.parametrize(
    "sentence",
    [
        "",
        "   ",
        "继续按上面的方案做，把测试补上",
        "这个方向可以，帮我补一下边界情况",
        "把函数抽出来，再加个类型注解",
    ],
)
def test_plain_sentences_do_not_hit(sentence: str) -> None:
    assert detect_direction_conflict(sentence) is False


def test_punctuation_and_case_do_not_matter() -> None:
    """标点/全角空格/大小写不该影响召回：先归一化再匹配。"""
    assert detect_direction_conflict("换个方向，") is True
    assert detect_direction_conflict("换个方向。") is True
    assert detect_direction_conflict("换个  方向") is True
