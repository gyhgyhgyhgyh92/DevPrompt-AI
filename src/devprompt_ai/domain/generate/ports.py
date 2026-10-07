"""GeneratePort 声明（MUST-06 落点：实现在 harness/llm.py）。"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class GenerationContext(BaseModel):
    """单套生成输入：压缩骨架（符号表摘要 + 取证结论 + 澄清），不含代码正文（MUST-09 精神）。"""

    sentence: str
    project_root: str
    level: Literal["A", "B", "C"]
    facts_summary: str = ""
    clarifications: dict[str, str] = Field(default_factory=dict)
    conservative: bool = False


class VariantDraft(BaseModel):
    """结构化方案（F-301 单套输出）。"""

    title: str
    body: str
    changes: list[str] = Field(default_factory=list)
    level: Literal["A", "B", "C"]


@runtime_checkable
class GeneratePort(Protocol):
    async def generate_single(self, ctx: GenerationContext) -> VariantDraft: ...
