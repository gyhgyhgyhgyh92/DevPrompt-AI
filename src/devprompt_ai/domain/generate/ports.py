"""GeneratePort 声明（MUST-06 落点：实现在 harness/llm.py）。"""

from __future__ import annotations

from typing import Literal, Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, Field, model_validator

Level: TypeAlias = Literal["A", "B", "C"]

# MUST-28 可输出档位仅允许从 A 起的前缀集：A→{A}、B→{A,B}、C→{A,B,C}（禁止跳档如 {B}、{A,C}）
VALID_LEVEL_SETS: tuple[frozenset[str], ...] = (
    frozenset({"A"}),
    frozenset({"A", "B"}),
    frozenset({"A", "B", "C"}),
)


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


class MultiVariantDraft(BaseModel):
    """三套同次调用输出（F-301：一次 LLM 调用共享同一份上下文）。

    校验：n∈[1,3]；档位无重复，且档位集合恰为可输出档位前缀集之一
    （MUST-28 不越级输出，见 VALID_LEVEL_SETS）。
    """

    variants: list[VariantDraft] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _levels_must_form_valid_prefix_set(self) -> MultiVariantDraft:
        levels = [v.level for v in self.variants]
        if len(set(levels)) != len(levels):
            raise ValueError(f"variants 存在重复档位：{levels}")
        if frozenset(levels) not in VALID_LEVEL_SETS:
            raise ValueError(
                f"档位集合 {sorted(set(levels))} 不是合法可输出档位前缀集"
                "（MUST-28：仅允许 {{A}}/{{A,B}}/{{A,B,C}}）"
            )
        return self


@runtime_checkable
class GeneratePort(Protocol):
    async def generate_single(self, ctx: GenerationContext) -> VariantDraft: ...

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level]
    ) -> MultiVariantDraft:
        """三套（或裁剪后 1~3 套）在同一次 LLM 调用中生成（F-301；阶段五 5C/T5-1）。

        契约：levels 由调用方按 resolve_level 推导——A→["A"]、B→["A","B"]、C→["A","B","C"]
        （见 domain/generate/variants.expand_levels；MUST-28 附注：仅 A 档=单套，三套同调
        不适用；escape/护栏保守路径请求 ["A"]）。实现必须保证：单次 LLM 调用；返回档位
        集合恰等于请求集合；按 A<B<C 单调排序。
        """
        ...
