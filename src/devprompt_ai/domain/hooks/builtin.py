"""内置 hook（2026-11-04）：把 service 里重复计算的横切逻辑搬进来。

第一个成员是取证摘要：``_act_generate`` 与 ``_rank_and_mark`` 各算一次，
每次都要遍历 7 项事实并截断证据。改成 after_retrieval 算一次、写进会话，
两处读缓存——这是本管线唯一有实证收益的插入点，其余横切点保持内联。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from devprompt_ai.domain.agent.action import AgentStep
from devprompt_ai.domain.hooks.detectors import (
    dead_end_hint,
    is_dead_end,
    needs_self_verify,
    self_verify_hint,
)
from devprompt_ai.domain.hooks.types import HookContext, HookPhase, HookResult

#: 单条证据在摘要里的截断长度（MUST-09 精神：控制进入 prompt 的体积）
EVIDENCE_PREVIEW = 80


def summarize_facts(data: Mapping[str, Any]) -> str:
    """把七项取证结果压成一行摘要：目标 + 每项真假与证据片段。

    纯函数，只读传入的映射——service 与 hook 共用同一实现，避免两处漂移。
    """
    parts = [
        f"{f['key']}={'真' if f['passed'] else '假'}（{str(f['evidence'])[:EVIDENCE_PREVIEW]}）"
        for f in data.get("facts", [])
    ]
    target = data.get("target") or {}
    name = target.get("name", "") if isinstance(target, Mapping) else ""
    path = target.get("path", "") if isinstance(target, Mapping) else ""
    return f"目标：{name}@{path}；" + "；".join(parts)


class FactsSummaryHook:
    """after_retrieval：取证完成后生成一次摘要，供生成与打分复用。"""

    name = "facts_summary"
    phase: HookPhase = "after_retrieval"

    def run(self, ctx: HookContext) -> HookResult:
        if not ctx.data.get("facts"):
            return HookResult(skipped=True)
        return HookResult(data={"facts_summary": summarize_facts(ctx.data)})


class DetectorHook:
    """post_tool：自检与死路提醒（E9–E10）。只给纠偏建议，终止仍由主循环决定。

    steps 由调用方放进 ctx.data（主循环的实时步骤序列）；
    委派 blocked/partial 已记 FAILED（service._step_outcome），死路检测在线。
    """

    name = "detectors"
    phase: HookPhase = "post_tool"

    def run(self, ctx: HookContext) -> HookResult:
        steps: tuple[AgentStep, ...] = tuple(ctx.data.get("steps") or ())
        actions = [step.action.value for step in steps]
        # 死路比「只读连击」更具体，先判死路
        if is_dead_end([(step.action.value, step.outcome.value) for step in steps]):
            return HookResult(verdict="correct", reason=dead_end_hint(actions[-1]))
        if needs_self_verify(actions):
            return HookResult(verdict="correct", reason=self_verify_hint())
        return HookResult()
