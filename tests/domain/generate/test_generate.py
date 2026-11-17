"""F-301 单套生成域层测试：上下文/方案模型 + 模板路由 + 结构守卫。

2026-11-11 单套输出后，档位概念（Level / resolve_level）已删除：
常规轮次恒由 B 标准版产出，A 保守版仅作异常兜底。
"""

import pytest
from pydantic import ValidationError

from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft
from devprompt_ai.domain.generate.templates import (
    CONSERVATIVE_TEMPLATE,
    STANDARD_TEMPLATE,
    template_for,
)
from devprompt_ai.harness.guardrails import validate_variant


def test_context_and_draft_models() -> None:
    GenerationContext(
        sentence="改提交按钮颜色",
        project_root=".",
        facts_summary="all ok",
        clarifications={},
    )
    draft = VariantDraft(title="t", body="b", changes=["c1"], fallback=True)
    assert draft.changes == ["c1"]
    assert draft.fallback is True
    # 档位字段已删除：旧数据里的 level 不再被接受为模型字段
    assert "level" not in GenerationContext.model_fields
    assert "level" not in VariantDraft.model_fields


def test_draft_rejects_malformed_payload() -> None:
    with pytest.raises(ValidationError):
        VariantDraft(title="t", body="b", changes="not-a-list")  # type: ignore[arg-type]


def test_template_routing_is_single_path_with_fallback() -> None:
    """常规恒为 B；只有 fallback=True 才切到 A（唯一兜底通道）。"""
    assert template_for() is STANDARD_TEMPLATE
    assert template_for(fallback=False) is STANDARD_TEMPLATE
    assert template_for(fallback=True) is CONSERVATIVE_TEMPLATE


def test_template_user_message_contains_evidence_fields() -> None:
    ctx = GenerationContext(
        sentence="改提交按钮颜色",
        project_root=".",
        facts_summary="SubmitButton@src/ui/button.tsx:12",
        clarifications={"token_defined": "用 --color-primary-500"},
        target_excerpt="12|export function SubmitButton() {}",
        design_tokens=("src/styles/antdTheme.ts:8:colorError",),
    )
    user = STANDARD_TEMPLATE.build_user(ctx, "zh-CN")
    assert ctx.sentence in user
    assert "src/ui/button.tsx" in user
    assert "233|" not in user  # 证据块只含真实片段
    assert "colorError" in user


def test_validate_variant_rejects_empty_shell() -> None:
    validate_variant(VariantDraft(title="t", body="b", changes=["c1"]))  # 合法不抛
    with pytest.raises(GenerationError):
        validate_variant(VariantDraft(title="  ", body="b", changes=["c1"]))
