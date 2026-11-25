"""Reflection 指标纯聚合（2026-11-23）：把 events.jsonl 与会话轮次压成比率。

不读文件、不碰 SQLite；I/O 在 ``scripts/measure_reflection.py``。分母为 0 时
返回 ``None``，由调用方输出 ``no-data``，不把「没有样本」写成 0（MUST-11d）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReflectionMetrics:
    sessions: int = 0
    rounds_total: int = 0
    rounds_sessions: int = 0
    answer_total: int = 0
    answer_option: int = 0
    answer_best_guess: int = 0
    answer_free_text: int = 0
    answer_multi_select: int = 0
    repeat_repeated: int = 0
    repeat_total: int = 0
    recall_total: int = 0
    recall_hit: int = 0
    recorded_project: int = 0
    recorded_global: int = 0
    preference_events: int = 0

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator > 0 else None

    @property
    def has_data(self) -> bool:
        return any(
            (
                self.sessions,
                self.answer_total,
                self.repeat_total,
                self.recall_total,
                self.recorded_project,
                self.recorded_global,
                self.preference_events,
            )
        )

    @property
    def repeat_ask_rate(self) -> float | None:
        return self._ratio(self.repeat_repeated, self.repeat_total)

    @property
    def avg_clarification_rounds(self) -> float | None:
        return self._ratio(self.rounds_total, self.rounds_sessions)

    @property
    def free_text_ratio(self) -> float | None:
        return self._ratio(self.answer_free_text, self.answer_total)

    @property
    def option_ratio(self) -> float | None:
        return self._ratio(self.answer_option, self.answer_total)

    @property
    def best_guess_ratio(self) -> float | None:
        return self._ratio(self.answer_best_guess, self.answer_total)

    @property
    def recall_hit_rate(self) -> float | None:
        return self._ratio(self.recall_hit, self.recall_total)


def _as_int(value: object) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return 0


def aggregate_reflection(
    events: Sequence[Mapping[str, Any]],
    *,
    session_rounds: Sequence[int] = (),
) -> ReflectionMetrics:
    """聚合计数型事件；不认的 event 名静默跳过，便于日志向前兼容。"""
    answers = option = best_guess = free_text = multi = 0
    repeated = repeat_total = 0
    recall_total = recall_hit = 0
    project = global_ = preference = 0

    for event in events:
        if not isinstance(event, Mapping):
            continue
        name = str(event.get("event", ""))
        if name == "clarification.answer_classified":
            answers += _as_int(event.get("total"))
            option += _as_int(event.get("option"))
            best_guess += _as_int(event.get("best_guess"))
            free_text += _as_int(event.get("free_text"))
            multi += _as_int(event.get("multi_select"))
        elif name == "followup.expect_unmet":
            repeated += _as_int(event.get("repeated"))
            repeat_total += _as_int(event.get("total"))
        elif name == "reflection.recalled":
            recall_total += 1
            if _as_int(event.get("hits")) > 0:
                recall_hit += 1
        elif name == "reflection.recorded":
            scope = str(event.get("scope", ""))
            if scope == "project":
                project += 1
            elif scope == "global":
                global_ += 1
        elif name == "reflection.preference":
            preference += 1

    positive_rounds = [value for value in session_rounds if value > 0]
    return ReflectionMetrics(
        sessions=len(session_rounds),
        rounds_total=sum(positive_rounds),
        rounds_sessions=len(positive_rounds),
        answer_total=answers,
        answer_option=option,
        answer_best_guess=best_guess,
        answer_free_text=free_text,
        answer_multi_select=multi,
        repeat_repeated=repeated,
        repeat_total=repeat_total,
        recall_total=recall_total,
        recall_hit=recall_hit,
        recorded_project=project,
        recorded_global=global_,
        preference_events=preference,
    )
