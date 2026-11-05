"""极简 hook 管线（domain/hooks/pipeline）测试。

覆盖：正常合并、异常跳过、超时跳过、skipped 不合并，以及「失败不阻断后续 hook」。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.hooks.pipeline import HookPipeline
from devprompt_ai.domain.hooks.types import (
    Hook,
    HookContext,
    HookPhase,
    HookResult,
    HookVerdict,
)


class StaticHook(Hook):
    def __init__(
        self, name: str, payload: dict[str, Any], *, phase: HookPhase = "after_turn"
    ) -> None:
        self.name = name
        self.phase = phase
        self.payload = payload

    def run(self, ctx: HookContext) -> HookResult:
        return HookResult(data=self.payload)


class RaisingHook(Hook):
    def __init__(self, name: str, *, phase: HookPhase = "after_turn") -> None:
        self.name = name
        self.phase = phase

    def run(self, ctx: HookContext) -> HookResult:
        raise RuntimeError("boom")


class SlowHook(Hook):
    def __init__(self, name: str, *, phase: HookPhase = "after_turn") -> None:
        self.name = name
        self.phase = phase

    def run(self, ctx: HookContext) -> HookResult:
        import time

        time.sleep(0.3)
        return HookResult(data={"slow": True})


class SkippingHook(Hook):
    def __init__(self, name: str, *, phase: HookPhase = "after_turn") -> None:
        self.name = name
        self.phase = phase

    def run(self, ctx: HookContext) -> HookResult:
        return HookResult(skipped=True)


def _ctx(phase: HookPhase = "after_turn") -> HookContext:
    return HookContext(phase=phase, session_state="AGENTIC", data={})


async def test_pipeline_merges_hook_output() -> None:
    pipeline = HookPipeline([StaticHook("a", {"x": 1}), StaticHook("b", {"y": 2})])

    merged = await pipeline.run("after_turn", _ctx())

    assert merged == {"x": 1, "y": 2}
    assert [run.outcome for run in pipeline.runs] == ["completed", "completed"]


async def test_failing_hook_is_isolated() -> None:
    pipeline = HookPipeline([RaisingHook("bad"), StaticHook("good", {"kept": True})])

    merged = await pipeline.run("after_turn", _ctx())

    assert merged == {"kept": True}
    assert [run.outcome for run in pipeline.runs] == ["failed", "completed"]


async def test_timeout_drops_only_that_hook() -> None:
    pipeline = HookPipeline(
        [SlowHook("slow"), StaticHook("fast", {"kept": True})], timeout_seconds=0.05
    )

    merged = await pipeline.run("after_turn", _ctx())

    assert merged == {"kept": True}
    assert pipeline.runs[0].outcome == "timed_out"


async def test_skipped_hook_merges_nothing() -> None:
    pipeline = HookPipeline([SkippingHook("skip"), StaticHook("keep", {"a": 1})])

    merged = await pipeline.run("after_turn", _ctx())

    assert merged == {"a": 1}
    assert pipeline.runs[0].outcome == "skipped"


async def test_phase_filtering() -> None:
    pipeline = HookPipeline(
        [
            StaticHook("later", {"x": 1}, phase="after_generate"),
            StaticHook("now", {"y": 2}, phase="after_turn"),
        ]
    )

    merged = await pipeline.run("after_turn", _ctx())

    assert merged == {"y": 2}


async def test_no_hooks_is_noop() -> None:
    merged = await HookPipeline().run("after_retrieval", _ctx("after_retrieval"))

    assert dict(merged) == {}


class VerdictHook(Hook):
    """按指定 verdict 返回的 hook，用于验证三态合并。"""

    def __init__(
        self,
        name: str,
        *,
        verdict: HookVerdict = "allow",
        reason: str = "",
        payload: dict[str, Any] | None = None,
        phase: HookPhase = "post_tool",
    ) -> None:
        self.name = name
        self.verdict = verdict
        self.reason = reason
        self.payload = payload or {}
        self.phase = phase

    def run(self, ctx: HookContext) -> HookResult:
        return HookResult(
            data=self.payload,
            verdict=self.verdict,
            reason=self.reason,
        )


async def test_halt_short_circuits_and_keeps_merged_data() -> None:
    pipeline = HookPipeline(
        [
            VerdictHook("first", payload={"x": 1}),
            VerdictHook("halt", verdict="halt", reason="证据与目标不符", payload={"y": 2}),
            VerdictHook("never", payload={"z": 3}),
        ]
    )

    outcome = await pipeline.run_phase("post_tool", _ctx("post_tool"))

    assert outcome.verdict == "halt"
    assert outcome.reason == "证据与目标不符"
    assert dict(outcome.data) == {"x": 1, "y": 2}
    assert [run.name for run in pipeline.runs] == ["first", "halt"]


async def test_correct_keeps_first_reason() -> None:
    pipeline = HookPipeline(
        [
            VerdictHook("a", verdict="correct", reason="先补取证"),
            VerdictHook("b", verdict="correct", reason="后一条不覆盖"),
        ]
    )

    outcome = await pipeline.run_phase("post_tool", _ctx("post_tool"))

    assert outcome.verdict == "correct"
    assert outcome.reason == "先补取证"


async def test_failure_and_timeout_never_escalate_to_halt() -> None:
    pipeline = HookPipeline([RaisingHook("bad", phase="post_tool")], timeout_seconds=0.05)

    outcome = await pipeline.run_phase("post_tool", _ctx("post_tool"))

    assert outcome.verdict == "allow"
    assert outcome.reason == ""


async def test_run_still_returns_only_data() -> None:
    pipeline = HookPipeline([VerdictHook("c", verdict="correct", reason="r", payload={"k": 1})])

    merged = await pipeline.run("post_tool", _ctx("post_tool"))

    assert dict(merged) == {"k": 1}
