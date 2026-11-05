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
    #: 多轮历史块（build_context 装配，已按预算裁剪且不含原句/绝对路径）
    history_block: str = ""
    #: L2 记忆 + 偏好投影（build_context 装配）
    memory_block: str = ""
    #: 上一轮三套方案正文（2026-11-04 多轮继承，≤2000 字符）：
    #: 「B 档第 2 条改成 X」这类迭代指令没有它就无法定位到具体哪一条。
    previous_variants: str = ""
    #: 上一轮推荐判定摘要（2026-11-05）：marked / reason / gap / 各档分数。
    #: 回答「为什么选 B」必须有它，否则模型只能如实说「上下文里没有依据」。
    ranking_summary: str = ""


ClaimKind: TypeAlias = Literal["file", "symbol", "token", "line"]


class Claim(BaseModel):
    """方案正文里的一条可核对断言（2026-11-04 证据账本）。

    模型在生成同一次调用里逐条声明「我引用了什么」，生成后由 ``match_claims``
    对取证结果核账——C 档承诺「行号 + token 出处」（MUST-28），这是兑现它的机器校验。
    """

    kind: ClaimKind
    #: 文件相对路径 / 符号名 / 样式 token / "路径:行号"，必须与正文原文一致
    target: str
    note: str = ""


class ReplyOutput(BaseModel):
    """纯回答输出（2026-11-05）：只有正文，没有 title/changes/claims/level。

    与 ``VariantDraft`` 分开定义，是为了让「回答」在类型层就不可能被当成方案落库。
    """

    text: str = Field(min_length=1)


class VariantDraft(BaseModel):
    """结构化方案（F-301 单套输出）。"""

    title: str
    body: str
    changes: list[str] = Field(default_factory=list)
    level: Literal["A", "B", "C"]
    #: 正文引用的逐条断言；缺省空表示模型未声明（旧 mock / 非 C 档），不参与判定。
    claims: list[Claim] = Field(default_factory=list)


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
        # 多轮（2026-10-20）：单套允许任意档位（沿用上一轮选定的方向，不越级由
        # plan_levels 的 min(preferred, level) 保证）；多套仍必须是 MUST-28 前缀集。
        if len(levels) > 1 and frozenset(levels) not in VALID_LEVEL_SETS:
            raise ValueError(
                f"档位集合 {sorted(set(levels))} 不是合法可输出档位前缀集"
                "（MUST-28：仅允许 {{A}}/{{A,B}}/{{A,B,C}}）"
            )
        return self


@runtime_checkable
class GeneratePort(Protocol):
    async def generate_single(self, ctx: GenerationContext) -> VariantDraft: ...

    async def answer(self, ctx: GenerationContext) -> str:
        """纯回答（2026-11-05）：只产出文字，不产生方案。

        与 ``generate_single`` 共用 ``GenerationContext``——回答「为什么选 B」需要
        ``previous_variants`` 与 ``history_block``，这两个字段已存在，不新增类型。
        """
        ...

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
