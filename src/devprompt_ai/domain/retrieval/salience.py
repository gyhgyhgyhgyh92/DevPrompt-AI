"""路径重排（I3）：实现文件优先、测试/文档降权、每文件限流。

目的：ripgrep 命中里，测试与文档经常淹没真正的实现文件；不改候选上限（MUST-09），
只在同一批候选内调整顺序。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

_SRC_BOOST: Final[float] = 1.08
_TEST_WEIGHT: Final[float] = 0.62
_DOC_WEIGHT: Final[float] = 0.72
_FIXTURE_WEIGHT: Final[float] = 0.55
_PER_FILE_LIMIT: Final[int] = 2


def path_weight(path: str) -> float:
    lowered = path.replace("\\", "/").lower()
    name = lowered.rsplit("/", 1)[-1]
    if "/test" in lowered or name.startswith("test_") or name.endswith("_test.py"):
        return _TEST_WEIGHT
    if "/fixture" in lowered or "/fixtures/" in lowered:
        return _FIXTURE_WEIGHT
    if name.endswith((".md", ".rst", ".txt")):
        return _DOC_WEIGHT
    if lowered.startswith("src/") or "/src/" in lowered:
        return _SRC_BOOST
    return 1.0


def rerank(
    scores: Mapping[str, float],
    *,
    per_file_limit: int = _PER_FILE_LIMIT,
) -> list[tuple[str, float]]:
    """按加权分排序，每个文件最多保留前 N 条（路径相同视为同一文件）。"""
    weighted = [(key, score * path_weight(key)) for key, score in scores.items()]
    weighted.sort(key=lambda pair: pair[1], reverse=True)

    counts: dict[str, int] = {}
    kept: list[tuple[str, float]] = []
    for key, score in weighted:
        path = key.split(":", 1)[0]
        if counts.get(path, 0) >= per_file_limit:
            continue
        counts[path] = counts.get(path, 0) + 1
        kept.append((key, score))
    return kept
