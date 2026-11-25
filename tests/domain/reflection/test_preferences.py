"""澄清回答偏好提取（2026-11-23）：分类、阈值、项目/全局隐私分流。"""

from __future__ import annotations

import dataclasses

from devprompt_ai.domain.reflection.preferences import (
    AnswerKind,
    ClarificationSignal,
    classify_answer,
    signals_from_answers,
    signals_from_payload,
    summarize_preferences,
)


def _answer(
    answer: str,
    *,
    header: str = "方案",
    key: str = "scope",
    labels: tuple[str, ...] = ("最小改动", "激进改版"),
    best_guess: str = "最小改动",
    multi_select: bool = False,
) -> ClarificationSignal:
    return classify_answer(
        key=key,
        header=header,
        best_guess=best_guess,
        option_labels=labels,
        multi_select=multi_select,
        answer=answer,
        round_index=1,
    )


def test_classifies_option_best_guess_and_free_text() -> None:
    option = _answer("最小改动")
    guess = classify_answer(
        key="other",
        header="方案",
        best_guess="先只改按钮",
        option_labels=("最小改动", "激进改版"),
        multi_select=False,
        answer="先只改按钮",
        round_index=1,
    )
    free = _answer("别加新依赖，按最小改动来", key="third")

    assert option.kind is AnswerKind.OPTION
    assert option.labels == ("最小改动",)
    assert guess.kind is AnswerKind.BEST_GUESS
    assert free.kind is AnswerKind.FREE_TEXT
    assert free.labels == ()
    assert "不加依赖" in free.tendencies
    assert "最小改动" in free.tendencies


def test_best_guess_only_when_not_an_option() -> None:
    signal = classify_answer(
        key="scope",
        header="方案",
        best_guess="先只改按钮",
        option_labels=("最小改动", "激进改版"),
        multi_select=False,
        answer="先只改按钮",
        round_index=2,
    )

    assert signal.kind is AnswerKind.BEST_GUESS
    assert signal.labels == ()
    assert signal.round_index == 2


def test_multi_select_splits_and_keeps_all_chosen_labels() -> None:
    signal = _answer(
        "最小改动, 保持兼容",
        labels=("最小改动", "保持兼容", "激进改版"),
        multi_select=True,
    )

    assert signal.kind is AnswerKind.OPTION
    assert signal.labels == ("最小改动", "保持兼容")
    assert signal.multi_select is True


def test_single_select_does_not_split_on_comma() -> None:
    signal = _answer("最小改动, 保持兼容", multi_select=False)

    assert signal.kind is AnswerKind.FREE_TEXT
    assert signal.labels == ()


def test_short_and_decisive_flags() -> None:
    short = _answer("你决定", key="a", best_guess="")
    long = _answer("我想先把范围压到只改这个按钮，其他页面先不动", key="b", best_guess="")

    assert short.short is True
    assert short.decisive is True
    assert long.short is False
    assert long.decisive is False


def test_threshold_needs_two_of_last_five() -> None:
    one = summarize_preferences([_answer("最小改动")])
    two = summarize_preferences([_answer("最小改动"), _answer("最小改动")])

    assert one.project_bits == ()
    assert one.global_bits == ()
    assert one.total == 1
    assert any("回答偏好" in bit for bit in two.project_bits)
    assert any("最小改动" in bit for bit in two.project_bits)
    assert any("偏好点选项" in bit for bit in two.global_bits)


def test_project_keeps_labels_global_keeps_only_style() -> None:
    summary = summarize_preferences([_answer("最小改动"), _answer("最小改动")])

    project = "\n".join(summary.project_bits)
    global_ = "\n".join(summary.global_bits)
    assert "回答偏好：方案=最小改动（2/2）" in project
    assert "决策倾向：最小改动（2/2）" in project
    assert "最小改动" not in global_
    assert "方案" not in global_
    assert "回答风格" in global_


def test_free_text_tendency_goes_project_not_global() -> None:
    summary = summarize_preferences(
        [
            _answer("别加新依赖，只改前端", key="a", best_guess=""),
            _answer("不加依赖，只改前端", key="b", best_guess=""),
        ]
    )

    project = "\n".join(summary.project_bits)
    global_ = "\n".join(summary.global_bits)
    assert "不加依赖" in project
    assert "只改前端" in project
    assert "常自由输入" in global_
    assert "不加依赖" not in global_
    assert "只改前端" not in global_


def test_signals_from_answers_skips_blank_and_aligns_unknowns() -> None:
    unknowns = [
        {
            "key": "scope",
            "header": "改动范围",
            "best_guess": "最小改动",
            "multi_select": False,
            "options": [
                {"label": "最小改动", "description": "只动当前文件"},
                {"label": "激进改版", "description": "一并重构"},
            ],
        }
    ]

    signals = signals_from_answers(
        unknowns,
        {"scope": "最小改动", "other": "   "},
        round_index=3,
    )

    assert len(signals) == 1
    assert signals[0].key == "scope"
    assert signals[0].header == "改动范围"
    assert signals[0].kind is AnswerKind.OPTION
    assert signals[0].round_index == 3


def test_signals_from_payload_round_trips() -> None:
    signal = _answer("最小改动")
    loaded = signals_from_payload([dataclasses.asdict(signal)])

    assert loaded == [signal]


def test_signals_from_payload_tolerates_bad_kind() -> None:
    loaded = signals_from_payload([{"key": "k", "kind": "unknown"}])

    assert len(loaded) == 1
    assert loaded[0].kind is AnswerKind.FREE_TEXT
