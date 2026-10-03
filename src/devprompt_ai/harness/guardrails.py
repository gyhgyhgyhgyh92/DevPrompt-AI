"""输出校验（harness 层）：决策/生成结果的最后防线。

结构校验由 pydantic 模型承担（port.py）；此处做跨字段语义校验。
"""

from __future__ import annotations

from devprompt_ai.domain.decision.port import RankComponentsOutput
from devprompt_ai.domain.errors import GenerationError


def validate_ranking(out: RankComponentsOutput, candidate_count: int) -> None:
    """排序输出必须恰好覆盖全部候选（少排/多排均属格式非法）。"""
    if len(out.order) != candidate_count:
        raise GenerationError(
            "排序输出数量与候选数不符",
            code=4003,
            context={"expected": candidate_count, "got": len(out.order)},
        )
