"""极简 hook 管线（2026-11-04，外环监督 2026-11-05）。

逐 hook 执行，单个 hook 超时或抛异常时**只丢弃它自己的产出**，不影响后续 hook 与主流程。
超时与异常一律视为 ``allow``——监督层自身故障不得升级成业务中断。

合并规则：

- ``halt``：短路后续 hook，立即返回（已合并的 data 保留）；
- ``correct``：取第一条非空 reason，其余 correct 不覆盖；
- ``allow``：只合并 data。

分层约束（MUST-06）：本模块不得 import observability —— 失败上报通过注入的
``on_result`` 回调交给调用方（service 层负责 emit），领域层只做排序与隔离。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from devprompt_ai.domain.hooks.types import Hook, HookContext, HookPhase, HookVerdict

#: 单 hook 默认墙钟预算。三个 hook 都是本地内存操作，5 秒已是异常级别的宽松值。
DEFAULT_HOOK_TIMEOUT_SECONDS: Final[float] = 5.0


@dataclass(frozen=True, slots=True)
class HookRun:
    """一次执行的观测记录（供日志与测试断言）。"""

    name: str
    outcome: str  # completed / failed / timed_out / skipped
    duration_ms: int


@dataclass(frozen=True, slots=True)
class HookOutcome:
    """一个阶段的汇总：合并后的数据 + 最强的对外环建议。"""

    data: Mapping[str, Any] = field(default_factory=dict)
    verdict: HookVerdict = "allow"
    reason: str = ""


class HookPipeline:
    """按阶段执行 hook 并合并产出。"""

    def __init__(
        self,
        hooks: Sequence[Hook] = (),
        *,
        timeout_seconds: float = DEFAULT_HOOK_TIMEOUT_SECONDS,
        on_result: Callable[[HookRun], None] | None = None,
    ) -> None:
        self._hooks = list(hooks)
        self._timeout = timeout_seconds
        self._on_result = on_result
        self.runs: list[HookRun] = []

    def register(self, hook: Hook) -> None:
        self._hooks.append(hook)

    async def run(self, phase: HookPhase, ctx: HookContext) -> Mapping[str, Any]:
        """兼容入口：只返回合并后的 data（现有调用方零改动）。"""
        return (await self.run_phase(phase, ctx)).data

    async def run_phase(self, phase: HookPhase, ctx: HookContext) -> HookOutcome:
        """执行该阶段全部 hook，返回合并数据与最强建议（同名键后者覆盖）。"""
        merged: dict[str, Any] = {}
        verdict: HookVerdict = "allow"
        reason = ""
        for hook in self._hooks:
            if hook.phase != phase:
                continue
            started = time.monotonic()
            outcome = "completed"
            result = None
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(hook.run, ctx), timeout=self._timeout
                )
            except TimeoutError:
                outcome = "timed_out"
            except Exception:  # noqa: BLE001 - 单个 hook 失败绝不阻断主流程
                outcome = "failed"
            duration_ms = int((time.monotonic() - started) * 1000)
            if result is not None and result.skipped:
                outcome = "skipped"
            record = HookRun(name=hook.name, outcome=outcome, duration_ms=duration_ms)
            self.runs.append(record)
            if self._on_result is not None:
                self._on_result(record)
            if outcome in {"failed", "timed_out"}:
                continue
            if result is None:
                continue
            merged.update(result.data)
            if result.verdict == "halt":
                return HookOutcome(
                    data=merged,
                    verdict="halt",
                    reason=result.reason or f"{hook.name} 要求终止本轮",
                )
            if result.verdict == "correct" and verdict == "allow":
                verdict = "correct"
                reason = result.reason
        return HookOutcome(data=merged, verdict=verdict, reason=reason)
