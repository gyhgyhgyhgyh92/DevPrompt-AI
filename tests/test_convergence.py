"""三判据收敛检测（domain/agent/convergence）纯函数测试。

覆盖：样本不足不判定、动作重复、事实停滞、决策无依据、
「先警告后熔断」（无 L2 记录时 L3 降级为 L2）。
"""

from devprompt_ai.domain.agent.action import AgentAction, AgentStep, StepOutcome
from devprompt_ai.domain.agent.convergence import (
    REPEAT_ABORT_STEPS,
    REPEAT_WARN_STEPS,
    STALL_WARN_STEPS,
    evaluate_convergence,
)

#: 交替动作序列，用于隔离「动作重复」判据，只测目标判据。
VARIED_ACTIONS: tuple[AgentAction, ...] = (
    AgentAction.RETRIEVE,
    AgentAction.PROBE,
    AgentAction.GENERATE,
    AgentAction.RANK,
    AgentAction.RETRIEVE,
    AgentAction.PROBE,
    AgentAction.GENERATE,
    AgentAction.RANK,
)


def make_step(
    index: int,
    action: AgentAction = AgentAction.PROBE,
    *,
    outcome: StepOutcome = StepOutcome.OK,
    facts_passed: int = 0,
    decided_by_evidence: bool = True,
) -> AgentStep:
    return AgentStep(
        index=index,
        action=action,
        outcome=outcome,
        duration_ms=1,
        facts_passed=facts_passed,
        decided_by_evidence=decided_by_evidence,
    )


def test_below_min_steps_is_not_stall() -> None:
    steps = [make_step(0), make_step(1)]
    verdict = evaluate_convergence(steps, warned_at_l2=False)
    assert verdict.level == 0
    assert not verdict.should_abort


def test_repeated_action_warns_and_aborts_only_after_warning() -> None:
    at_warn = [make_step(i, AgentAction.GENERATE) for i in range(REPEAT_WARN_STEPS)]
    warn_verdict = evaluate_convergence(at_warn, warned_at_l2=False)
    assert warn_verdict.level == 2
    assert not warn_verdict.should_abort

    at_abort = [make_step(i, AgentAction.GENERATE) for i in range(REPEAT_ABORT_STEPS)]
    # 没有 L2 记录 → 不熔断（先警告后熔断）
    assert evaluate_convergence(at_abort, warned_at_l2=False).should_abort is False
    assert evaluate_convergence(at_abort, warned_at_l2=True).should_abort is True


def test_fact_stagnation_warns() -> None:
    steps = [make_step(i, VARIED_ACTIONS[i], facts_passed=3) for i in range(STALL_WARN_STEPS)]
    verdict = evaluate_convergence(steps, warned_at_l2=False)
    assert verdict.level >= 2
    assert not verdict.should_abort
    assert "事实数" in verdict.reason


def test_fact_growth_is_healthy() -> None:
    actions = [AgentAction.RETRIEVE, AgentAction.PROBE, AgentAction.GENERATE, AgentAction.RANK]
    steps = [make_step(i, actions[i % len(actions)], facts_passed=i) for i in range(4)]
    assert evaluate_convergence(steps, warned_at_l2=False).level == 0


def test_blind_decisions_warn() -> None:
    # facts_passed 成对推进（0,0,1,1,2,2），隔离「事实停滞」判据，只测「决策无依据」
    steps = [
        make_step(
            i,
            VARIED_ACTIONS[i],
            facts_passed=i // 2,
            decided_by_evidence=False,
        )
        for i in range(STALL_WARN_STEPS)
    ]
    verdict = evaluate_convergence(steps, warned_at_l2=False)
    assert verdict.level >= 2
    assert "依据" in verdict.reason


def test_varied_actions_with_progress_are_not_aborting() -> None:
    steps = [make_step(i, action, facts_passed=7) for i, action in enumerate(VARIED_ACTIONS)]
    verdict = evaluate_convergence(steps, warned_at_l2=True)
    assert not verdict.should_abort
