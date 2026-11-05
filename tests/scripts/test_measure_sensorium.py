"""统计脚本的纯函数（2026-11-05）。

接线判定与护栏上限都从这里出结论，判错会直接把错误阈值带进配置，故单独钉住。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_sensorium.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("measure_sensorium", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load()


def _row(
    state: str,
    score: float | None,
    *,
    level: str = "C",
    undeclared: bool = False,
    tokens: int = 0,
) -> dict[str, Any]:
    sensorium: dict[str, Any] = {} if score is None else {"score": score}
    return {
        "state": state,
        "summary": {
            "level": level,
            "claims": {"total": 2, "covered": 2, "undeclared": undeclared},
            "sensorium": sensorium,
        },
        "usage": {"llm_tokens": tokens},
    }


def test_percentile_edges() -> None:
    assert script._percentile([], 50) == 0.0
    assert script._percentile([4.0], 95) == 4.0
    assert script._percentile([0.0, 10.0], 50) == 5.0


def test_not_ready_when_samples_insufficient() -> None:
    rows = [_row("DONE", 0.9) for _ in range(5)] + [_row("ABORTED", 0.1) for _ in range(3)]
    report = script._summarize(rows)
    assert report["fuse_ready"] is False
    assert report["scored_turns"] == 8


def test_ready_when_all_thresholds_met() -> None:
    rows = [_row("DONE", 0.9) for _ in range(20)] + [_row("ABORTED", 0.1) for _ in range(3)]
    report = script._summarize(rows)
    assert report["fuse_ready"] is True
    assert report["separation"] == 0.8


def test_falls_back_to_quartile_when_aborted_insufficient() -> None:
    rows = [_row("DONE", 0.9 - index * 0.05) for index in range(20)]
    report = script._summarize(rows)
    assert report["aborted_n"] == 0
    assert report["abnormal_basis"].startswith("最低四分位组")
    assert report["abnormal_n"] == 5


def test_claim_rate_and_budget_suggestion() -> None:
    rows = [
        _row("DONE", 0.9, undeclared=True),
        _row("DONE", 0.9),
        _row("DONE", 0.9),
        _row("DONE", 0.9),
        _row("DONE", 0.9, tokens=10_000),
    ]
    report = script._summarize(rows)
    assert report["c_turns"] == 5
    assert report["undeclared_turns"] == 1
    assert report["claim_rate"] == 0.2
    # p95=10000 → max(30000, 15000) → 30000（按 5000 取整）
    assert report["budget_suggestion"] == 30_000
