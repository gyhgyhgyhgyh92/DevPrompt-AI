"""循环收尾接线测试：A2 六道闸（STEER 弹回）、A8 超窗压一次重发、B11 摘要折叠。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.generate.ports import (
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.service import ForgeService
from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols


class StubGenerator(FakeGenerator):
    """记录收到的上下文；第一次抛超窗错误，第二次成功。"""

    def __init__(self) -> None:
        self.contexts: list[GenerationContext] = []

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level], locale: str = "zh-CN"
    ) -> MultiVariantDraft:
        self.contexts.append(ctx)
        if len(self.contexts) == 1:
            raise RuntimeError("prompt is too long: context length exceeded")
        return MultiVariantDraft(
            variants=[VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels]
        )


def _service(gen: ForgeService | StubGenerator) -> ForgeService:
    from devprompt_ai.harness.process import SymbolTableProvider

    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=gen,  # type: ignore[arg-type]
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


async def test_generate_retries_once_with_shrunk_context() -> None:
    """A8：超窗错误触发「压一次重发一次」，重发时 previous_variants 被丢弃。"""
    gen = StubGenerator()
    svc = _service(gen)

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "done"
    assert len(gen.contexts) == 2
    assert gen.contexts[1].previous_variants == ""


async def test_non_overflow_error_is_not_retried() -> None:
    """非超窗错误原样抛出（optimize 兜底转 ABORTED），不得当超窗重试。"""

    class BoomGenerator(FakeGenerator):
        async def generate_variants(
            self, ctx: GenerationContext, levels: list[Level], locale: str = "zh-CN"
        ) -> MultiVariantDraft:
            raise RuntimeError("boom: invalid api key")

    svc = _service(BoomGenerator())
    with pytest.raises(RuntimeError, match="invalid api key"):
        await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")


async def test_finish_gate_bounces_deliver_while_steer_pending() -> None:
    """A2：纠偏未消化时 DELIVER 被弹回；纠偏清空后放行。"""
    svc, _store = await _service_with_data()
    session = _session_of(svc)

    blocked = svc._evaluate_finish_gate(session)
    session.data["hook_correction"] = "先补取证再生成"
    pending = svc._evaluate_finish_gate(session)

    assert blocked.allowed is True
    assert pending.allowed is False
    assert pending.detail == "先补取证再生成"


async def _service_with_data() -> tuple[ForgeService, dict[str, Any]]:
    from devprompt_ai.harness.process import SymbolTableProvider

    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    return svc, {}


def _session_of(svc: ForgeService) -> Any:
    store = svc._sessions  # noqa: SLF001 - 测试观测点
    return next(iter(store.items.values()))


async def test_llm_digest_collapses_dropped_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """B11：开关打开且压缩触发时，窗口外旧轮折成一段摘要（置于最旧位）。"""
    from devprompt_ai.domain.context.build_context import TurnSummary
    from devprompt_ai.harness.process import SymbolTableProvider

    calls: list[str] = []

    async def fake_summarize(cfg: AppConfig, history: str, **_kw: object) -> tuple[str, bool]:
        calls.append(history)
        return "旧轮摘要：把按钮改蓝并补了测试。", False

    monkeypatch.setattr("devprompt_ai.service.summarize_history", fake_summarize)
    summaries = [
        TurnSummary(
            turn_id=f"t{i}",
            turn_index=i,
            target=f"sym{i}",
            conclusion=f"第{i}轮结论",
        )
        for i in range(10)
    ]

    svc = ForgeService(
        cfg=AppConfig(_env_file=None, summary_llm_enabled=True),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    out = await svc._maybe_llm_digest(  # noqa: SLF001 - 直测私有装配逻辑
        _session_stub(),
        summaries,
        estimated_tokens=svc.config.context_window_tokens,
        shrunk=False,
    )

    assert len(calls) == 1
    assert len(out) == 9  # 摘要 1 段 + 保留的 8 轮（recent 2 + digest 6）
    assert out[0].conclusion.startswith("旧轮摘要")
    assert out[0].turn_index == 1, "摘要段承接被丢弃的最旧轮次"
    assert "第0轮结论" in calls[0]


def _session_stub() -> Any:
    class _S:
        data: dict[str, Any] = {"turn_anchor": None}

    return _S()


def test_step_outcome_marks_failed_delegation() -> None:
    """E10 数据源：委派 blocked/partial 记 FAILED，死路检测因此在线。"""
    from devprompt_ai.domain.agent.action import AgentAction, StepOutcome

    session = _session_stub()
    session.data["delegation"] = {"status": "blocked"}

    assert ForgeService._step_outcome(AgentAction.DELEGATE, session) is StepOutcome.FAILED  # noqa: SLF001
    session.data["delegation"] = {"status": "ok"}
    assert ForgeService._step_outcome(AgentAction.DELEGATE, session) is StepOutcome.OK  # noqa: SLF001
    assert ForgeService._step_outcome(AgentAction.RETRIEVE, session) is StepOutcome.OK  # noqa: SLF001


def test_request_budget_assertion_trips_on_oversized_prompt() -> None:
    """A7：prompt 估算超窗口预算 → RequestBudgetError（A8 压缩重发闭环接手）。"""
    from devprompt_ai.domain.context.budget import RequestBudgetError
    from devprompt_ai.harness.llm import _assert_request_budget

    tiny = AppConfig(_env_file=None, context_window_tokens=100)  # type: ignore[call-arg]
    with pytest.raises(RequestBudgetError):
        _assert_request_budget(tiny, "SYS", "x" * 4000)  # noqa: SLF001

    normal = AppConfig(_env_file=None)  # type: ignore[call-arg]
    _assert_request_budget(normal, "SYS", "短 prompt")  # noqa: SLF001


async def test_context_layers_off_skips_delta() -> None:
    """context_layers_enabled 关闭：不注入 <context-update>（恢复改造前行为）。"""

    class QuietGenerator(StubGenerator):
        async def generate_variants(
            self, ctx: GenerationContext, levels: list[Level], locale: str = "zh-CN"
        ) -> MultiVariantDraft:
            self.contexts.append(ctx)
            return MultiVariantDraft(
                variants=[
                    VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels
                ]
            )

    gen = QuietGenerator()
    from devprompt_ai.harness.process import SymbolTableProvider

    svc = ForgeService(
        cfg=AppConfig(_env_file=None, context_layers_enabled=False),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert gen.contexts
    assert "<context-update" not in gen.contexts[0].history_block


async def test_tail_anchor_injected_after_compaction() -> None:
    """B13/B14：历史被压缩时，权威块出现在 history_block 尾部（与摘要冲突以本块为准）。"""

    class QuietGenerator(StubGenerator):
        async def generate_variants(
            self, ctx: GenerationContext, levels: list[Level], locale: str = "zh-CN"
        ) -> MultiVariantDraft:
            self.contexts.append(ctx)
            return MultiVariantDraft(
                variants=[
                    VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels
                ]
            )

    from devprompt_ai.harness.process import SymbolTableProvider

    gen = QuietGenerator()
    svc = ForgeService(
        cfg=AppConfig(_env_file=None, context_window_tokens=400, max_state_tokens=200),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    await svc.optimize(
        "local", ".", f"把提交按钮改成 primary-500，{'保留现有布局与文案' * 40}", request_id="r1"
    )

    assert gen.contexts
    text = gen.contexts[0].history_block
    assert "以本块为准" in text, "压缩轮必须重注入权威块"
    assert text.rstrip().endswith("</task-anchor>"), "权威块必须在消息尾部"


async def test_append_violation_warns_but_continues() -> None:
    """MUST-11c 检测面：伪造被改写的历史前缀 → 告警事件但装配照常完成。"""
    svc, _store = await _service_with_data()
    session = _session_of(svc)
    session.data["context_turn_indexes"] = [99]

    payload = await svc._assemble_context(session)  # noqa: SLF001

    assert payload.history_block, "违规只告警，装配不得中断"
    assert session.data["context_turn_indexes"] != [99], "基线被本轮真实序列覆盖"


async def test_checkpoint_sink_receives_step_payload() -> None:
    """阶段7：每 5 步的 checkpoint 经 sink 落 run_events；sink 故障不阻断主循环。"""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def sink(session_id: str, payload: dict[str, Any]) -> None:
        calls.append((session_id, payload))

    svc, _store = await _service_with_data()
    svc.checkpoint_sink = sink
    session = _session_of(svc)

    from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome

    steps = [
        AgentStep(
            index=i,
            action=AgentAction.RETRIEVE,
            outcome=StepOutcome.OK,
            duration_ms=1,
            facts_passed=0,
        )
        for i in range(5)
    ]
    await svc._emit_checkpoint(session, steps, AgentAction.RETRIEVE, "r1")  # noqa: SLF001

    assert calls and calls[0][0] == session.session_id
    assert calls[0][1]["step"] == 5

    async def boom(_sid: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("sink down")

    svc.checkpoint_sink = boom
    await svc._emit_checkpoint(session, steps, AgentAction.RETRIEVE, "r2")  # noqa: SLF001


async def test_quiet_abort_settles_turn_memory() -> None:
    """阶段7：异常中断也要沉淀——turn_memory 已写入（下一轮可回看）。"""

    class BoomGenerator(FakeGenerator):
        async def generate_variants(
            self, ctx: GenerationContext, levels: list[Level], locale: str = "zh-CN"
        ) -> MultiVariantDraft:
            raise RuntimeError("boom")

    from devprompt_ai.harness.process import SymbolTableProvider

    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=BoomGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    with pytest.raises(RuntimeError, match="boom"):
        await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    session = _session_of(svc)
    assert str(session.state) == "ABORTED"
    assert session.data.get("turn_memory") is not None


async def test_delegate_goes_through_coordinator_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段9：工单过调度闸执行成功；闸拒绝（占位冲突）时降级通知不阻断。"""
    from devprompt_ai.runtime.coordinator import DelegationCoordinator

    svc, store = await _service_with_data()
    session = _session_of(svc)
    events: list[dict[str, Any]] = []

    async def notify(_session: Any, _progress: Any, text: str) -> None:
        events.append({"text": text})

    monkeypatch.setattr("devprompt_ai.service._notify", notify)

    # 占住同范围文件 → can_run False → 调度闸拒绝
    svc._coordinator._inflight.update({"src/ui/button.tsx"})  # noqa: SLF001
    await svc._act_delegate(session, progress=None)
    assert any("调度闸拒绝" in item["text"] for item in events)

    # 释放占位后正常执行（确定性 worker 成功）
    svc._coordinator = DelegationCoordinator()
    await svc._act_delegate(session, progress=None)
    assert session.data["delegation"]["status"] == "ok"
