"""GeneratePort 声明（MUST-06 落点：实现在 harness/llm.py）。"""

from __future__ import annotations

from typing import Literal, Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale


class GenerationContext(BaseModel):
    """单套生成输入：压缩骨架（符号表摘要 + 取证结论 + 澄清），不含代码正文（MUST-09 精神）。

    例外（2026-11-11）：``target_excerpt`` 携带目标位置的**有界代码片段**。原因是四段式
    方案的「定位」与「实施」两段必须写出组件属性与「原代码 → 新代码」，纯骨架做不到。
    MUST-09 约束的是「候选 → 决策层 state」的体积，本字段只走 GeneratePort，不进
    ``facts_summary``，故决策层 state 不受影响。
    """

    sentence: str
    project_root: str
    facts_summary: str = ""
    clarifications: dict[str, str] = Field(default_factory=dict)
    conservative: bool = False
    #: 多轮历史块（build_context 装配，已按预算裁剪且不含原句/绝对路径）
    history_block: str = ""
    #: L2 记忆 + 偏好投影（build_context 装配）
    memory_block: str = ""
    #: 上一轮方案正文（2026-11-04 多轮继承，≤2000 字符）：
    #: 「上一条改成 X」这类迭代指令没有它就无法定位到具体哪一条。
    previous_variants: str = ""
    #: 上一轮推荐判定摘要（2026-11-05）：marked / reason / gap / 各档分数。
    #: 回答「为什么这样改」必须有它，否则模型只能如实说「上下文里没有依据」。
    ranking_summary: str = ""
    #: 目标代码片段（带行号，2026-11-11）。只供生成层，理由见类 docstring。
    target_excerpt: str = ""
    #: 设计令牌证据（rg 命中行，2026-11-11），供「一致性检查」段引用。
    design_tokens: tuple[str, ...] = ()
    #: 领域包 id（2026-11-14 领域包）：模板据此切换分段语义、领域指令与 claims 规则。
    #: 默认 "code"——旧调用方零改动；领域指令/分段文案由模板按包内 i18n 键渲染。
    domain_id: str = "code"
    #: 命中技能正文（2026-11-21）：由 service 按匹配度挑选并截断，独立于检索证据预算。
    skill_block: str = ""
    #: 历史经验区块（2026-11-22 Reflection）：service 从外部经验库召回、裁剪后渲染，
    #: 与技能区块并列拼进 system；空串表示本轮无可注入经验（或该能力未启用）。
    reflection_block: str = ""
    #: 视觉生成风格（2026-11-14 多模态）：仅 visual 域消费；空串 = 通用风格。
    #: 合法值见 domain.domains.packs.visual.VISUAL_STYLES；模板按
    #: ``domain.visual.style.{style_id}`` i18n 键切领域指令，非法值回退通用。
    style_id: str = ""
    #: 图生图参考图（2026-11-14 多模态）：base64 data URL，仅 visual 域消费；
    #: 生成层据此构造多模态消息（上限/格式由请求契约层校验）。
    images: tuple[str, ...] = ()


ClaimKind: TypeAlias = Literal["file", "symbol", "token", "line", "absence"]


class Claim(BaseModel):
    """方案正文里的一条可核对断言（2026-11-04 证据账本）。

    模型在生成同一次调用里逐条声明「我引用了什么」，生成后由 ``match_claims``
    对取证结果核账——这是兑现「路径 + 行号 + token 出处」承诺的机器校验。
    """

    kind: ClaimKind
    #: 文件相对路径 / 符号名 / 样式 token / "路径:行号"，必须与正文原文一致
    target: str
    note: str = ""
    #: ``kind="absence"`` 时必填：被否定的引用类别（2026-11-06）。
    #: 没有它就无法判断「未找到」该去核哪一项取证；``test`` 对应测试文件存在性。
    negates: Literal["file", "symbol", "token", "line", "test"] | None = None

    @model_validator(mode="after")
    def _check_negates(self) -> Claim:
        """absence 必须指明类别；非 absence 不允许携带 negates（防止语义混淆）。"""
        if self.kind == "absence" and self.negates is None:
            raise ValueError("kind=absence 必须同时给出 negates（被否定的引用类别）")
        if self.kind != "absence" and self.negates is not None:
            raise ValueError("negates 只用于 kind=absence")
        return self


class ReplyOutput(BaseModel):
    """纯回答输出（2026-11-05）：只有正文，没有 title/changes/claims/fallback。

    与 ``VariantDraft`` 分开定义，是为了让「回答」在类型层就不可能被当成方案落库。
    """

    text: str = Field(min_length=1)


class VariantDraft(BaseModel):
    """结构化方案（F-301 单套输出）。"""

    title: str
    body: str
    changes: list[str] = Field(default_factory=list)
    #: 正文引用的逐条断言；缺省空表示模型未声明（旧 mock），不参与判定。
    claims: list[Claim] = Field(default_factory=list)
    #: 是否由兜底模板（A）产出（2026-11-11）：True 表示本轮主流程失败后降级，
    #: 快照必须披露「已降级为保守输出」。
    fallback: bool = False


@runtime_checkable
class GeneratePort(Protocol):
    async def generate_single(
        self,
        ctx: GenerationContext,
        locale: Locale = DEFAULT_LOCALE,
        *,
        fallback: bool = False,
    ) -> VariantDraft:
        """唯一生成入口（2026-11-11）：常规轮次恒用 B 标准版模板。

        ``fallback=True`` 仅在主流程抛错或产出无效时由调用方传入，改用 A 保守版
        模板重试一次，产物标记 ``VariantDraft.fallback``。
        """
        ...

    async def answer(self, ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
        """纯回答（2026-11-05）：只产出文字，不产生方案。

        与 ``generate_single`` 共用 ``GenerationContext``——回答「为什么这样改」需要
        ``previous_variants`` 与 ``history_block``，这两个字段已存在，不新增类型。
        """
        ...
