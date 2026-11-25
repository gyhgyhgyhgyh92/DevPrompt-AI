"""Reflection 指标（2026-11-23）：从 events.jsonl 与 forge_sessions 聚合。

用法：
    uv run python scripts/measure_reflection.py
    uv run python scripts/measure_reflection.py --log-dir ./.logs --db ~/.devprompt-ai/devprompt.db

只读；不打印答案、选项、路径或原句。分母为 0 的指标输出 no-data。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.metrics.reflection import ReflectionMetrics, aggregate_reflection
from devprompt_ai.observability.logging import event_log_path


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_session_rounds(db_path: Path) -> list[int]:
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute("SELECT payload FROM forge_sessions").fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    rounds: list[int] = []
    for (payload,) in rows:
        try:
            data = json.loads(str(payload))
        except ValueError:
            continue
        value = data.get("rounds") if isinstance(data, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            rounds.append(value)
    return rounds


def _ratio(value: float | None, numerator: int, denominator: int) -> str:
    if value is None:
        return "no-data"
    return f"{value * 100:.1f}% ({numerator}/{denominator})"


def _print_metrics(metrics: ReflectionMetrics) -> None:
    print("Reflection metrics")
    print(f"sessions: {metrics.sessions}")
    print(
        "repeat_ask_rate: "
        + _ratio(metrics.repeat_ask_rate, metrics.repeat_repeated, metrics.repeat_total)
    )
    if metrics.avg_clarification_rounds is None:
        print("avg_clarification_rounds: no-data")
    else:
        print(
            f"avg_clarification_rounds: {metrics.avg_clarification_rounds:.2f}"
            f" ({metrics.rounds_sessions} sessions)"
        )
    print(
        "free_text_ratio: "
        + _ratio(metrics.free_text_ratio, metrics.answer_free_text, metrics.answer_total)
    )
    print(
        "option_ratio: " + _ratio(metrics.option_ratio, metrics.answer_option, metrics.answer_total)
    )
    print(
        "best_guess_ratio: "
        + _ratio(metrics.best_guess_ratio, metrics.answer_best_guess, metrics.answer_total)
    )
    print(
        "recall_hit_rate: "
        + _ratio(metrics.recall_hit_rate, metrics.recall_hit, metrics.recall_total)
    )
    print(f"recorded: project={metrics.recorded_project}, global={metrics.recorded_global}")
    print(f"preference_events: {metrics.preference_events}")


def main(argv: list[str] | None = None) -> None:
    cfg = AppConfig()
    parser = argparse.ArgumentParser(description="Reflection 指标")
    parser.add_argument("--log-dir", default=cfg.log_dir)
    parser.add_argument("--db", default=cfg.db_path)
    args = parser.parse_args(argv)

    events = _read_events(event_log_path(args.log_dir))
    db_path = Path(args.db).expanduser()
    metrics = aggregate_reflection(events, session_rounds=_read_session_rounds(db_path))
    if not metrics.has_data:
        print("no-data (no sessions or reflection/clarification events found)")
        return
    _print_metrics(metrics)


if __name__ == "__main__":
    main()
