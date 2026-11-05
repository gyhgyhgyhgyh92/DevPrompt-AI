"""输出校验（harness 层）：决策/生成结果的最后防线。

结构校验由 pydantic 模型承担（port.py）；此处做跨字段语义校验。
"""

from __future__ import annotations

from collections.abc import Sequence

from devprompt_ai.domain.decision.port import RankComponentsOutput
from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.domain.generate.claims import ClaimReport, match_claims
from devprompt_ai.domain.generate.ports import VariantDraft
from devprompt_ai.domain.models import FactResult


def validate_ranking(out: RankComponentsOutput, candidate_count: int) -> None:
    """排序输出必须恰好覆盖全部候选（少排/多排均属格式非法）。"""
    if len(out.order) != candidate_count:
        raise GenerationError(
            "排序输出数量与候选数不符",
            code=4003,
            context={"expected": candidate_count, "got": len(out.order)},
        )


def validate_variant(draft: VariantDraft) -> None:
    """单套输出校验：标题/正文非空（MUST-17 禁空壳输出）。"""
    if not draft.title.strip() or not draft.body.strip():
        raise GenerationError("生成方案标题或正文为空", code=4003, context={"level": draft.level})


def validate_claims(draft: VariantDraft, facts: Sequence[FactResult]) -> ClaimReport:
    """方案断言对账（2026-11-04）。

    只返回报告、不抛异常：证据缺口是**披露项**而不是流程失败——降档由调用方决定，
    重新生成反而会让模型为了凑覆盖率而删掉有价值的引用。
    """
    return match_claims(draft.claims, facts)
