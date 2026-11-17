"""交付归属（E11）：交付门按「改动属于谁、验证覆盖如何」判定。

与 `gate.py` 的分工：gate 看方案本身（claims/锚点），本模块看**改动归属**与
波及测试覆盖；两者都只降标记、不阻断交付（MUST-30 精神）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateColor(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True, slots=True)
class Attribution:
    """一次交付的改动归属快照。"""

    owned_files: tuple[str, ...] = ()
    external_files: tuple[str, ...] = ()
    owned_failed: tuple[str, ...] = ()
    owned_unverified: tuple[str, ...] = ()
    uncovered_impact: tuple[str, ...] = field(default_factory=tuple)


def evaluate_attribution(data: Attribution) -> GateColor:
    """owned 有失败/未验证 → RED；外部阻塞或波及未覆盖 → YELLOW；否则 GREEN。"""
    if data.owned_failed or data.owned_unverified:
        return GateColor.RED
    if data.external_files or data.uncovered_impact:
        return GateColor.YELLOW
    return GateColor.GREEN


def describe(color: GateColor, data: Attribution) -> str:
    """给用户看的一句话披露；不出现文件正文，只出现数量与类别。"""
    if color is GateColor.GREEN:
        return "改动均已验证，可交付。"
    if color is GateColor.RED:
        count = len(data.owned_failed) + len(data.owned_unverified)
        return f"有 {count} 个自有改动未验证，不标推荐。"
    return f"有 {len(data.external_files)} 个外部改动、{len(data.uncovered_impact)} 处波及未覆盖。"
