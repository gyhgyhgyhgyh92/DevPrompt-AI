"""澄清回答偏好提取（纯函数，零 I/O，MUST-06）。

回答反问时用户只有三种动作：点选项、采纳默认建议、自由输入。这里只做规则统计：
最近 ``PREF_WINDOW`` 次里同一偏好出现至少 ``PREF_MIN_COUNT`` 次才写成“习惯”，
避免一次偶然选择被当成长期偏好。

项目桶可以保留具体选项，全局桶只保留回答风格——后者跨项目复用，不能带出
项目里的选项名、问题标题、路径或自由文本原文。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

#: 只看最近 5 次回答；同一项至少出现 2 次才算习惯。
PREF_WINDOW: Final[int] = 5
PREF_MIN_COUNT: Final[int] = 2
#: 项目桶最多保留两个问题维度的选项偏好、两个决策倾向。
MAX_OPTION_BITS: Final[int] = 2
MAX_TENDENCY_BITS: Final[int] = 2
#: 短答阈值：中文字符数，够区分“只回一句”和“写了一段”。
SHORT_ANSWER_CHARS: Final[int] = 10
#: 与前端多选回填格式保持一致（FollowupForm.tsx 的 MULTI_SEP）。
MULTI_SEP: Final[str] = ", "

#: 只做可解释的关键词匹配，不调模型；命中即记标签，误判由窗口/阈值稀释。
TENDENCY_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("最小改动", ("最小", "少改", "保守", "不动接口", "复用现有", "只改这一处", "只改当前")),
    ("不加依赖", ("不加依赖", "无依赖", "零依赖", "不引入", "不新增", "别加")),
    ("只改前端", ("只改前端", "仅前端", "不动后端", "只改ui", "只改界面")),
    ("保持兼容", ("兼容", "不破坏", "向后兼容")),
)
_DECISIVE_HINTS: Final[tuple[str, ...]] = (
    "你决定",
    "你定",
    "随意",
    "都行",
    "看着办",
    "随便",
)


class AnswerKind(str, Enum):
    """一条回答的来源；自由输入不落原文，只留长度与倾向。"""

    OPTION = "option"
    BEST_GUESS = "best-guess"
    FREE_TEXT = "free-text"


@dataclass(frozen=True, slots=True)
class ClarificationSignal:
    """一轮里对某个澄清问题的回答摘要（可直接落 session.data）。"""

    key: str
    header: str
    kind: AnswerKind
    labels: tuple[str, ...] = ()
    tendencies: tuple[str, ...] = ()
    answer_chars: int = 0
    short: bool = False
    decisive: bool = False
    multi_select: bool = False
    round_index: int = 0


@dataclass(frozen=True, slots=True)
class PreferenceSummary:
    """项目/全局两组文案 + 计数；文案为空表示未过阈值。"""

    project_bits: tuple[str, ...] = ()
    global_bits: tuple[str, ...] = ()
    total: int = 0
    option: int = 0
    best_guess: int = 0
    free_text: int = 0
    multi_select: int = 0


def _split_multi(answer: str) -> list[str]:
    return [part.strip() for part in answer.split(MULTI_SEP) if part.strip()]


def _tendencies(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(
        tag for tag, keywords in TENDENCY_RULES if any(word in lowered for word in keywords)
    )


def classify_answer(
    *,
    key: str,
    header: str,
    best_guess: str,
    option_labels: Sequence[str],
    multi_select: bool,
    answer: str,
    round_index: int,
) -> ClarificationSignal:
    """把一条回答归类；选项/默认建议/自由输入三选一。"""
    text = answer.strip()
    labels = set(option_labels)
    parts = _split_multi(text) if multi_select else [text]
    chosen = tuple(part for part in parts if part in labels)
    all_options = bool(parts) and len(chosen) == len(parts)
    if all_options:
        kind = AnswerKind.OPTION
    elif best_guess and text == best_guess.strip():
        kind = AnswerKind.BEST_GUESS
    else:
        kind = AnswerKind.FREE_TEXT
    return ClarificationSignal(
        key=key,
        header=header.strip(),
        kind=kind,
        labels=chosen if kind is AnswerKind.OPTION else (),
        tendencies=_tendencies(text),
        answer_chars=len(text),
        short=0 < len(text) <= SHORT_ANSWER_CHARS,
        decisive=any(hint in text for hint in _DECISIVE_HINTS),
        multi_select=multi_select,
        round_index=round_index,
    )


def signals_from_answers(
    unknowns: Sequence[Mapping[str, Any]],
    answers: Mapping[str, str],
    *,
    round_index: int,
) -> list[ClarificationSignal]:
    """把 ``unknowns`` 与本次 ``answers`` 对齐成信号；空答案直接跳过。"""
    by_key = {
        str(item.get("key", "")): item
        for item in unknowns
        if isinstance(item, Mapping) and str(item.get("key", "")) != ""
    }
    out: list[ClarificationSignal] = []
    for key, answer in answers.items():
        text = str(answer or "").strip()
        if not text:
            continue
        question = by_key.get(str(key), {})
        options = question.get("options") or []
        labels = [
            str(option.get("label", ""))
            for option in options
            if isinstance(option, Mapping) and str(option.get("label", "")) != ""
        ]
        out.append(
            classify_answer(
                key=str(key),
                header=str(question.get("header", "") or ""),
                best_guess=str(question.get("best_guess", "") or ""),
                option_labels=labels,
                multi_select=bool(question.get("multi_select", False)),
                answer=text,
                round_index=round_index,
            )
        )
    return out


def _as_int(value: object) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return 0


def signals_from_payload(payload: Sequence[Mapping[str, Any]]) -> list[ClarificationSignal]:
    """从 ``session.data`` 里读回信号；坏行跳过，不让旁路数据拖垮收尾。"""
    out: list[ClarificationSignal] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        raw_kind = item.get("kind")
        if isinstance(raw_kind, AnswerKind):
            kind = raw_kind
        else:
            try:
                kind = AnswerKind(str(raw_kind))
            except ValueError:
                kind = AnswerKind.FREE_TEXT
        out.append(
            ClarificationSignal(
                key=str(item.get("key", "") or ""),
                header=str(item.get("header", "") or ""),
                kind=kind,
                labels=tuple(str(value) for value in (item.get("labels") or ())),
                tendencies=tuple(str(value) for value in (item.get("tendencies") or ())),
                answer_chars=_as_int(item.get("answer_chars")),
                short=bool(item.get("short", False)),
                decisive=bool(item.get("decisive", False)),
                multi_select=bool(item.get("multi_select", False)),
                round_index=_as_int(item.get("round_index")),
            )
        )
    return out


def _option_bits(recent: Sequence[ClarificationSignal], total: int, min_count: int) -> list[str]:
    counts: Counter[tuple[str, str]] = Counter()
    for signal in recent:
        if signal.kind is not AnswerKind.OPTION:
            continue
        header = signal.header or signal.key
        for label in signal.labels:
            counts[(header, label)] += 1
    best_by_header: dict[str, tuple[str, int]] = {}
    for (header, label), count in counts.items():
        current = best_by_header.get(header)
        if current is None or count > current[1] or (count == current[1] and label < current[0]):
            best_by_header[header] = (label, count)
    ranked = sorted(best_by_header.items(), key=lambda item: (-item[1][1], item[0]))
    bits = [
        f"回答偏好：{header}={label}（{count}/{total}）"
        for header, (label, count) in ranked[:MAX_OPTION_BITS]
        if count >= min_count
    ]
    return bits


def _tendency_bits(recent: Sequence[ClarificationSignal], total: int, min_count: int) -> list[str]:
    counts: Counter[str] = Counter(tag for signal in recent for tag in signal.tendencies)
    picked = [
        f"{tag}（{count}/{total}）"
        for tag, count in counts.most_common(MAX_TENDENCY_BITS)
        if count >= min_count
    ]
    return [f"决策倾向：{'、'.join(picked)}"] if picked else []


def _global_style_bits(
    recent: Sequence[ClarificationSignal],
    *,
    total: int,
    option: int,
    best_guess: int,
    free_text: int,
    multi_select: int,
    min_count: int,
) -> list[str]:
    bits: list[str] = []
    if option >= min_count:
        bits.append(f"偏好点选项（{option}/{total}）")
    if best_guess >= min_count:
        bits.append(f"常采纳默认建议（{best_guess}/{total}）")
    if free_text >= min_count:
        bits.append(f"常自由输入（{free_text}/{total}）")
    if multi_select >= min_count:
        bits.append(f"常多选（{multi_select}/{total}）")
    short = sum(1 for signal in recent if signal.short)
    if short >= min_count:
        bits.append(f"回答偏短（≤{SHORT_ANSWER_CHARS} 字，{short}/{total}）")
    decisive = sum(1 for signal in recent if signal.decisive)
    if decisive >= min_count:
        bits.append(f"常让你决定（{decisive}/{total}）")
    return [f"回答风格：{'、'.join(bits)}"] if bits else []


def summarize_preferences(
    signals: Sequence[ClarificationSignal],
    *,
    window: int = PREF_WINDOW,
    min_count: int = PREF_MIN_COUNT,
) -> PreferenceSummary:
    """按最近窗口汇总；未达阈值时只返回计数，不产出文案。"""
    recent = list(signals[-window:]) if window > 0 else list(signals)
    total = len(recent)
    counts = Counter(signal.kind for signal in recent)
    option = counts[AnswerKind.OPTION]
    best_guess = counts[AnswerKind.BEST_GUESS]
    free_text = counts[AnswerKind.FREE_TEXT]
    multi_select = sum(1 for signal in recent if signal.multi_select)
    if total < min_count:
        return PreferenceSummary(
            total=total,
            option=option,
            best_guess=best_guess,
            free_text=free_text,
            multi_select=multi_select,
        )

    project_bits: list[str] = [
        *_option_bits(recent, total, min_count),
        *_tendency_bits(recent, total, min_count),
        f"回答方式：点选项 {option}/{total}、采纳默认 {best_guess}/{total}、"
        f"自由输入 {free_text}/{total}",
    ]
    global_bits = _global_style_bits(
        recent,
        total=total,
        option=option,
        best_guess=best_guess,
        free_text=free_text,
        multi_select=multi_select,
        min_count=min_count,
    )
    return PreferenceSummary(
        project_bits=tuple(project_bits),
        global_bits=tuple(global_bits),
        total=total,
        option=option,
        best_guess=best_guess,
        free_text=free_text,
        multi_select=multi_select,
    )
