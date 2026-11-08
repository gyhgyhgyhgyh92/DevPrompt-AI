"""六维状态感知测试：边界（零步 / 全失败 / 零预算）与确定性。"""

from __future__ import annotations

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome
from devprompt_ai.domain.agent.sensorium import SensoriumInput, compute_sensorium


def _step(
    index: int,
    action: AgentAction = AgentAction.RETRIEVE,
    *,
    outcome: StepOutcome = StepOutcome.OK,
    evidence: bool = True,
) -> AgentStep:
    return AgentStep(
        index=index,
        action=action,
        outcome=outcome,
        duration_ms=10,
        facts_passed=0,
        decided_by_evidence=evidence,
    )


def test_empty_turn_is_neutral_not_success() -> None:
    snap = compute_sensorium(SensoriumInput())

    assert snap.momentum == 0.5, "零步不得冒充「一路顺利」"
    assert snap.pressure == 0.0
    assert snap.coverage == 0.0, "无断言不等于全覆盖"
    assert snap.complexity == 0.0
    assert snap.familiarity == 0.5, "冷启动给中性值"
    assert snap.stability == 1.0
    assert 0.0 <= snap.score <= 1.0


def test_all_failed_steps_lower_momentum_and_stability() -> None:
    steps = [_step(i, outcome=StepOutcome.FAILED, evidence=False) for i in range(4)]

    snap = compute_sensorium(SensoriumInput(steps=steps))

    assert snap.momentum == 0.0
    assert snap.stability < 0.5
    assert snap.score < 0.5


def test_pressure_uses_steps_only_when_budget_is_zero() -> None:
    steps = [_step(i) for i in range(12)]

    without_budget = compute_sensorium(SensoriumInput(steps=steps, max_steps=24))
    with_budget = compute_sensorium(
        SensoriumInput(steps=steps, max_steps=24, cost_tokens=90, cost_budget=100)
    )

    assert without_budget.pressure == 0.5
    assert with_budget.pressure > without_budget.pressure


def test_pressure_takes_max_of_absolute_and_relative() -> None:
    """E3/E4：小窗口下绝对占用高时，即使步数占比低压力也必须高。"""
    few_steps = compute_sensorium(
        SensoriumInput(steps=[_step(0)], max_steps=24, context_tokens=900, context_window=1000)
    )
    none_set = compute_sensorium(SensoriumInput(steps=[_step(0)], max_steps=24))

    assert few_steps.pressure == 0.9
    assert none_set.pressure < 0.1, "未设窗口时不参与绝对压力判定"


def test_coverage_reads_claim_report() -> None:
    assert compute_sensorium(SensoriumInput(claim_coverage=0.75)).coverage == 0.75
    assert compute_sensorium(SensoriumInput(claim_coverage=None)).coverage == 0.0


def test_complexity_grows_with_action_variety() -> None:
    same = [_step(i, AgentAction.RETRIEVE) for i in range(4)]
    varied = [
        _step(0, AgentAction.RETRIEVE),
        _step(1, AgentAction.PROBE),
        _step(2, AgentAction.GENERATE),
        _step(3, AgentAction.DELIVER),
    ]

    assert compute_sensorium(SensoriumInput(steps=same)).complexity == 0.0
    assert compute_sensorium(SensoriumInput(steps=varied)).complexity > 0.0


def test_familiarity_uses_notes_and_turn_depth() -> None:
    cold = compute_sensorium(SensoriumInput(notes_hit=0, turn_index=0))
    warm = compute_sensorium(SensoriumInput(notes_hit=5, turn_index=5))

    assert cold.familiarity == 0.5
    assert warm.familiarity == 1.0


def test_quality_marks_fallback_values() -> None:
    """回退值必须自带标记：零步 / 无断言不能被当成实测良好。"""
    empty = compute_sensorium(SensoriumInput())
    assert empty.quality.momentum == "no-data"
    assert empty.quality.coverage == "no-data"
    assert empty.quality.stability == "partial"

    measured = compute_sensorium(SensoriumInput(steps=[_step(0)], claim_coverage=0.5))
    assert measured.quality.momentum == "measured"
    assert measured.quality.coverage == "measured"
    assert measured.quality.stability == "measured"


def test_quality_does_not_leak_into_payload() -> None:
    """质量标记不进 payload：下游按 float 消费，混入字符串会破坏契约。"""
    payload = compute_sensorium(SensoriumInput()).as_payload()

    assert all(isinstance(value, float) for value in payload.values())


def test_snapshot_is_deterministic_and_bounded() -> None:
    data = SensoriumInput(
        steps=[_step(0), _step(1, AgentAction.PROBE, outcome=StepOutcome.FAILED)],
        max_steps=24,
        cost_tokens=30,
        cost_budget=100,
        claim_coverage=0.4,
        notes_hit=2,
        turn_index=3,
    )

    first = compute_sensorium(data)
    second = compute_sensorium(data)

    assert first == second
    for value in first.as_payload().values():
        assert 0.0 <= value <= 1.0
