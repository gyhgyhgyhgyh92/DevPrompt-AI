"""认知账本（B15）：本轮模型可自省状态的只读快照。

为什么量化：镜像每轮都进上下文，数值抖动会让字节变化、缓存前缀失效。
这里统一量化到 low / mid / high 三档，保证同一状态渲染结果字节稳定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from devprompt_ai.domain.context.task_contract import TaskContract

_LOW: Final[float] = 0.35
_HIGH: Final[float] = 0.7


@dataclass(frozen=True, slots=True)
class LedgerInput:
    contract: TaskContract
    turn_index: int = 0
    files_modified: int = 0
    verified: int = 0
    sensorium_score: float = 0.0
    risk: str = "low"
    trace: tuple[str, ...] = field(default_factory=tuple)


def quantize(value: float) -> str:
    if value < _LOW:
        return "low"
    if value < _HIGH:
        return "mid"
    return "high"


def build_ledger(data: LedgerInput) -> str:
    """生成固定字段、固定顺序的账本文本。"""
    coverage = f"{data.verified}/{data.files_modified}" if data.files_modified > 0 else "n/a"
    lines = [
        "【认知账本】",
        f"目标：{data.contract.objective}",
        f"状态：{data.contract.status.value}",
        f"轮次：{data.turn_index}",
        f"验证覆盖：{coverage}",
        f"稳定性：{quantize(data.sensorium_score)}",
        f"风险：{data.risk}",
    ]
    if data.trace:
        lines.append("最近轨迹：" + "；".join(data.trace[-3:]))
    return "\n".join(lines)
