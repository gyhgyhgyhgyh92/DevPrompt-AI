"""F-203/F-204 v1.1 编排逻辑测试（纯函数，Fake 注入）。"""

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.followup import (
    GuardrailState,
    UnknownItem,
    build_unknowns,
)
from devprompt_ai.domain.decision.port import FactJudgment, FactProbeOutput
from devprompt_ai.domain.models import FactResult


def _probe(*confs: float) -> FactProbeOutput:
    keys = [
        "target_file_exists",
        "symbol_in_file",
        "token_defined",
        "has_data_testid",
        "has_state_styles",
        "file_type_matches",
        "test_file_exists",
    ]
    return FactProbeOutput(
        judgments=[
            FactJudgment(key=k, passed=c >= 0.75, confidence=c)
            for k, c in zip(keys, confs, strict=True)
        ],
        overall_confidence=0.8,
    )


def _facts() -> list[FactResult]:
    return [
        FactResult("target_file_exists", True, "file=src/a.tsx"),
        FactResult("symbol_in_file", True, "src/a.tsx:12:SubmitButton"),
        FactResult("token_defined", False, "未找到"),
        FactResult("has_data_testid", True, "src/a.tsx:14:data-testid"),
        FactResult("has_state_styles", True, "src/a.tsx:20::hover"),
        FactResult("file_type_matches", True, "ext=.tsx"),
        FactResult("test_file_exists", False, "未找到"),
    ]


def test_failed_fact_becomes_unknown() -> None:
    items = build_unknowns(_probe(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9), _facts())
    assert [i.key for i in items] == ["token_defined", "test_file_exists"]
    assert items[0].ask != "" and items[0].reason != ""
    assert isinstance(items[0], UnknownItem)  # 导出类型可直接构造比较（4C 消费契约）


def test_low_confidence_fact_becomes_unknown() -> None:
    items = build_unknowns(_probe(0.9, 0.9, 0.9, 0.5, 0.9, 0.9, 0.9), _facts())
    assert any(i.key == "has_data_testid" for i in items)


def test_answered_key_skipped() -> None:
    items = build_unknowns(
        _probe(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9),
        _facts(),
        clarifications={"test_file_exists": "写到 src/ui/__tests__"},
    )
    assert all(i.key != "test_file_exists" for i in items)


def test_all_clear_yields_empty() -> None:
    facts = [
        FactResult(k, True, "ok")
        for k in (
            "target_file_exists",
            "symbol_in_file",
            "token_defined",
            "has_data_testid",
            "has_state_styles",
            "file_type_matches",
            "test_file_exists",
        )
    ]
    assert build_unknowns(_probe(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9), facts) == []


def test_guardrail_round_trigger() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    g = GuardrailState(rounds=10)
    assert g.should_trigger(cfg) is True
    assert GuardrailState(rounds=9).should_trigger(cfg) is False


def test_guardrail_cost_trigger_and_zero_disabled() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert GuardrailState(rounds=0, cost_tokens=5000).should_trigger(cfg) is False  # 预算 0=禁用
    rich = AppConfig(_env_file=None, followup_cost_budget=1000.0)  # type: ignore[call-arg]
    assert GuardrailState(rounds=0, cost_tokens=1000).should_trigger(rich) is True


def test_guardrail_reset() -> None:
    g = GuardrailState(rounds=10)
    g.reset()
    assert g.rounds == 0
