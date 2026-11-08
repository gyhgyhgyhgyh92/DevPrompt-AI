"""观测与自适应测试：相位收敛、策略映射、注意力质量、检测器与交付归属。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome
from devprompt_ai.domain.agent.phase_convergence import (
    PhaseClass,
    evaluate_phase,
    score_signals,
    select_tier,
)
from devprompt_ai.domain.agent.sensorium import (
    AttentionMetrics,
    SensoriumInput,
    compute_attention_quality,
    compute_sensorium,
    derive_strategy,
)
from devprompt_ai.domain.delivery.attribution import (
    Attribution,
    GateColor,
    describe,
    evaluate_attribution,
)
from devprompt_ai.domain.hooks.detectors import (
    dead_end_hint,
    is_dead_end,
    needs_self_verify,
    self_verify_hint,
)


def _step(
    index: int,
    action: AgentAction,
    *,
    outcome: StepOutcome = StepOutcome.OK,
    note: str = "",
    duration_ms: int = 10,
) -> AgentStep:
    return AgentStep(
        index=index,
        action=action,
        outcome=outcome,
        duration_ms=duration_ms,
        facts_passed=0,
        note=note,
    )


def test_tier_selection_scales_with_window() -> None:
    assert select_tier(200_000).n_low == 8
    assert select_tier(1_000_000).n_low == 25
    mid = select_tier(600_000)
    assert 8 < mid.n_low < 25


def test_productive_steps_score_higher() -> None:
    productive = [_step(i, AgentAction.GENERATE, note=f"n{i}") for i in range(10)]
    idle = [_step(i, AgentAction.RETRIEVE, note="same") for i in range(10)]

    assert score_signals(productive, PhaseClass.EXECUTE, window=6) > score_signals(
        idle, PhaseClass.EXECUTE, window=6
    )


def test_phase_changes_weighting() -> None:
    steps = [_step(i, AgentAction.RETRIEVE, note=f"n{i}") for i in range(10)]

    assert score_signals(steps, PhaseClass.EXECUTE, window=6) < score_signals(
        steps, PhaseClass.EXPLORE, window=6
    ), "只读步在执行期应被更低评价"


def test_low_score_hits_level_three_after_enough_turns() -> None:
    steps = [
        _step(i, AgentAction.RETRIEVE, outcome=StepOutcome.FAILED, note="same") for i in range(20)
    ]

    verdict = evaluate_phase(steps, phase=PhaseClass.EXECUTE, context_window=200_000)

    assert verdict.level == 3
    assert verdict.should_abort is True


def test_reasoning_active_downgrades_abort_to_kick() -> None:
    steps = [
        _step(i, AgentAction.RETRIEVE, outcome=StepOutcome.FAILED, note="same") for i in range(20)
    ]

    verdict = evaluate_phase(
        steps, phase=PhaseClass.EXECUTE, context_window=200_000, reasoning_active=True
    )

    assert verdict.level == 2
    assert verdict.reason == "reasoning-active"


def test_no_tool_stagnation_respects_reasoning() -> None:
    quiet = evaluate_phase([], phase=PhaseClass.PLAN, context_window=200_000, no_tool_count=5)
    reasoning = evaluate_phase(
        [], phase=PhaseClass.PLAN, context_window=200_000, no_tool_count=5, reasoning_active=True
    )

    assert quiet.level == 3
    assert reasoning.level == 2


def test_vetoes_cap_level() -> None:
    steps = [
        _step(i, AgentAction.RETRIEVE, outcome=StepOutcome.FAILED, note="same") for i in range(20)
    ]

    todo = evaluate_phase(
        steps, phase=PhaseClass.EXECUTE, context_window=200_000, todo_completed=True
    )
    awaiting = evaluate_phase(
        steps, phase=PhaseClass.EXECUTE, context_window=200_000, awaiting_verification=True
    )

    assert todo.level == 1
    assert awaiting.level == 1


def test_repeated_verification_raises_to_level_two() -> None:
    steps = [_step(i, AgentAction.RETRIEVE, note=f"n{i}") for i in range(8)]

    verdict = evaluate_phase(
        steps, phase=PhaseClass.EXECUTE, context_window=200_000, repeated_verification=True
    )

    assert verdict.level == 2


def test_strategy_is_continuous_and_measured_aware() -> None:
    high = compute_sensorium(
        SensoriumInput(
            steps=[
                _step(index, action)
                for index, action in enumerate(
                    (
                        AgentAction.RETRIEVE,
                        AgentAction.PROBE,
                        AgentAction.ASK,
                        AgentAction.GENERATE,
                        AgentAction.RANK,
                        AgentAction.DELIVER,
                        AgentAction.ABORT,
                        AgentAction.REPLY,
                    )
                )
            ]
        )
    )
    strategy = derive_strategy(high)
    assert strategy.reasoning_effort == "high", "复杂度高时用强推理"

    cold = compute_sensorium(SensoriumInput())
    cold_strategy = derive_strategy(cold)
    assert cold_strategy.reasoning_effort == "medium", "no-data 的 momentum 不当成低效"
    assert 0.0 <= cold_strategy.exploration_breadth <= 1.0
    assert 0.5 <= cold_strategy.commit_threshold <= 1.0


def test_attention_quality_penalizes_tool_storm() -> None:
    calm = AttentionMetrics(
        tool_density=0.2,
        unique_tool_ratio=0.9,
        avg_tool_result_chars=500,
        user_message_ratio=0.3,
    )
    storm = AttentionMetrics(
        tool_density=0.9,
        unique_tool_ratio=0.1,
        avg_tool_result_chars=9000,
        user_message_ratio=0.01,
        tool_storm="storm",
    )

    assert compute_attention_quality(calm) > compute_attention_quality(storm)
    assert compute_attention_quality(storm) < 0.3, "低质量应触发提前折叠"


def test_detectors() -> None:
    assert needs_self_verify(["retrieve", "probe", "retrieve"]) is True
    assert needs_self_verify(["retrieve", "generate"]) is False
    assert needs_self_verify([]) is False

    assert is_dead_end([("retrieve", "failed")] * 3) is True
    assert is_dead_end([("retrieve", "ok")] * 3) is False
    assert is_dead_end([("retrieve", "failed"), ("probe", "failed")] * 2) is False
    assert "读取" in self_verify_hint()
    assert "失败" in dead_end_hint("retrieve")


def test_attribution_colors() -> None:
    green = evaluate_attribution(Attribution(owned_files=("a.py",)))
    red = evaluate_attribution(Attribution(owned_files=("a.py",), owned_failed=("a.py",)))
    yellow = evaluate_attribution(Attribution(owned_files=("a.py",), uncovered_impact=("b.py",)))

    assert green is GateColor.GREEN
    assert red is GateColor.RED
    assert yellow is GateColor.YELLOW
    assert "未验证" in describe(red, Attribution(owned_failed=("a.py",)))
    assert "外部改动" in describe(yellow, Attribution(external_files=("b.py",)))
