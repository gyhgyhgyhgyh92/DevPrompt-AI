"""影响半径（I5）：反向 BFS，最多 3 跳。

输入是「反向依赖表」：`dst -> {src}`（谁依赖 dst）。超过 3 跳的「影响」噪声大于信号，
因此 max_hops 默认 3；hop0 是被改文件本身，不入结果。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

DEFAULT_MAX_HOPS: Final[int] = 3


def compute_impact(
    reverse_deps: Mapping[str, set[str]],
    changed: Iterable[str],
    *,
    max_hops: int = DEFAULT_MAX_HOPS,
    limit: int = 50,
) -> dict[str, int]:
    """返回 {依赖方路径: 跳数}；跳数从 1 开始。"""
    seen: dict[str, int] = {}
    frontier = [path for path in changed if path]
    for hop in range(1, max(1, max_hops) + 1):
        next_frontier: list[str] = []
        for path in frontier:
            for dependent in reverse_deps.get(path, ()):
                if dependent in seen or dependent in changed:
                    continue
                seen[dependent] = hop
                next_frontier.append(dependent)
                if len(seen) >= limit:
                    return seen
        frontier = next_frontier
        if not frontier:
            break
    return seen


def requires_verification(impact: Mapping[str, int]) -> set[str]:
    """1 跳必须验证；更远的按需（由交付门决定是否披露）。"""
    return {path for path, hop in impact.items() if hop <= 1}
