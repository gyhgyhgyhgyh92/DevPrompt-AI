"""离线归因脚本的纯函数（2026-11-05）。

三个口径直接决定「要不要为签名再花额度实测」，判错会把结论带偏，故单独钉住。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analyze_signature_impact.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("analyze_signature_impact", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load()


def _case(
    case_id: str,
    *,
    expected: str,
    top1: str,
    top5: list[str],
    hit: bool,
    in_pool: bool = True,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "expected": expected,
        "order0": top1,
        "top5": top5,
        "hit": hit,
        "expected_in_candidates": in_pool,
    }


def test_same_name_miss_counts_as_recoverable() -> None:
    rows = [
        _case(
            "a",
            expected="echo@src/click/utils.py",
            top1="echo@src/click/testing.py",
            top5=["echo@src/click/testing.py", "echo@src/click/utils.py"],
            hit=False,
        )
    ]
    result = script._analyze(rows)
    assert result["recoverable"] == ["a"]
    assert result["hopeless"] == []
    assert result["upper_accuracy"] == 1.0
    assert result["ambiguous"] == 1


def test_different_name_miss_is_hopeless() -> None:
    rows = [
        _case(
            "b",
            expected="echo@src/click/utils.py",
            top1="format_filename@src/click/utils.py",
            top5=["format_filename@src/click/utils.py"],
            hit=False,
        )
    ]
    result = script._analyze(rows)
    assert result["recoverable"] == []
    assert result["hopeless"] == ["b"]
    assert result["upper_accuracy"] == 0.0


def test_ceiling_uses_expected_in_candidates() -> None:
    rows = [
        _case("c", expected="a@x.py", top1="a@x.py", top5=["a@x.py"], hit=True),
        _case(
            "d",
            expected="b@y.py",
            top1="c@z.py",
            top5=["c@z.py"],
            hit=False,
            in_pool=False,
        ),
    ]
    result = script._analyze(rows)
    assert result["accuracy"] == 0.5
    assert result["ceiling"] == 0.5
    assert result["upper_accuracy"] == 0.5
