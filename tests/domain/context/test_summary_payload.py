"""轮次摘要的观测三块（2026-11-05）。

断言：六维快照与断言对账随摘要落库、只取白名单数值键、且不含原句与绝对路径（MUST-19）。
"""

from __future__ import annotations

from devprompt_ai.domain.context import summary_from_turn


def test_observations_landed_in_summary() -> None:
    summary = summary_from_turn(
        {
            "sensorium": {
                "momentum": 0.5,
                "pressure": 0.25,
                "coverage": 1.0,
                "complexity": 0.0,
                "familiarity": 0.75,
                "stability": 0.5,
                "score": 0.42,
                "extra": "不该落库",
            },
            "claim_report": {
                "total": 3,
                "covered": 2,
                "coverage": 0.67,
                "undeclared": False,
                "uncovered": ["D:\\abs\\path.py:12"],
                "summary": "断言文本",
            },
            "level": "C",
        }
    )
    assert summary["sensorium"]["score"] == 0.42
    assert "extra" not in summary["sensorium"]
    assert summary["claims"] == {"total": 3, "covered": 2, "undeclared": False}
    assert summary["level"] == "C"
    # 断言文本与绝对路径不进库（MUST-19）
    assert "uncovered" not in summary["claims"]
    assert "abs" not in str(summary)


def test_missing_observations_are_empty() -> None:
    summary = summary_from_turn({})
    assert summary["sensorium"] == {}
    assert summary["claims"] == {}
    assert summary["level"] == ""
