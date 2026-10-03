"""DecisionPort 输出契约测试（pydantic 模型校验，无 LLM）。"""

import pytest
from pydantic import ValidationError

from devprompt_ai.domain.decision.port import (
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)


def test_rank_output_accepts_permutation() -> None:
    out = RankComponentsOutput(order=[2, 0, 1], confidence=0.83)
    assert out.order[0] == 2


def test_rank_output_rejects_non_permutation() -> None:
    with pytest.raises(ValidationError):
        RankComponentsOutput(order=[0, 0, 1], confidence=0.9)  # 重复索引


def test_rank_output_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        RankComponentsOutput(order=[0, 3], confidence=0.9)  # 越界


def test_confidence_must_be_0_to_1() -> None:
    with pytest.raises(ValidationError):
        RankComponentsOutput(order=[0], confidence=1.5)


def test_fact_probe_output() -> None:
    out = FactProbeOutput(
        judgments=[FactJudgment(key="target_file_exists", passed=True, confidence=0.9)],
        overall_confidence=0.88,
    )
    assert out.judgments[0].passed is True


def test_score_prompts_variant_keys() -> None:
    out = ScorePromptsOutput(
        scores=[
            VariantScore(variant="A", score=2, confidence=0.7),
            VariantScore(variant="B", score=3, confidence=0.8),
            VariantScore(variant="C", score=4, confidence=0.9),
        ]
    )
    assert [s.variant for s in out.scores] == ["A", "B", "C"]


def test_score_must_be_0_to_4() -> None:
    with pytest.raises(ValidationError):
        VariantScore(variant="A", score=5, confidence=0.9)
