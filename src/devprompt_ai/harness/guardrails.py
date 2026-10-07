"""输出校验（harness 层）：决策/生成结果的最后防线。

结构校验由 pydantic 模型承担（port.py）；此处做跨字段语义校验。
"""

from __future__ import annotations

from devprompt_ai.domain.decision.port import RankComponentsOutput
from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.domain.generate.ports import VariantDraft


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
