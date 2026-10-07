"""F-301 单套生成域层测试：档位裁定 + 模板 + 输出模型。"""

import pytest
from pydantic import ValidationError

from devprompt_ai.domain.errors import GenerationError
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft
from devprompt_ai.domain.generate.variants import resolve_level
from devprompt_ai.harness.guardrails import validate_variant


def test_resolve_level_c_when_facts_complete() -> None:
    assert resolve_level(has_symbol=True, facts_complete=True) == "C"


def test_resolve_level_b_when_symbol_only() -> None:
    assert resolve_level(has_symbol=True, facts_complete=False) == "B"


def test_resolve_level_a_when_raw() -> None:
    assert resolve_level(has_symbol=False, facts_complete=False) == "A"


def test_context_and_draft_models() -> None:
    ctx = GenerationContext(
        sentence="改提交按钮颜色",
        project_root=".",
        level="A",
        facts_summary="all ok",
        clarifications={},
    )
    draft = VariantDraft(title="t", body="b", changes=["c1"], level="A")
    assert ctx.level == "A" and draft.changes == ["c1"]
    with pytest.raises(ValidationError):
        VariantDraft(title="t", body="b", changes=[], level="D")  # type: ignore[arg-type]  # 非法档位


def test_template_by_level() -> None:
    from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL

    ctx = GenerationContext(
        sentence="改提交按钮颜色",
        project_root=".",
        level="B",
        facts_summary="SubmitButton@src/ui/button.tsx:12",
        clarifications={"token_defined": "用 --color-primary-500"},
    )
    for _level, tpl in TEMPLATE_BY_LEVEL.items():
        user = tpl.build_user(ctx)
        assert ctx.sentence in user
    assert "src/ui/button.tsx" in TEMPLATE_BY_LEVEL["B"].build_user(ctx)


def test_validate_variant_rejects_empty_shell() -> None:
    validate_variant(VariantDraft(title="t", body="b", changes=["c1"], level="A"))  # 合法不抛
    with pytest.raises(GenerationError):
        validate_variant(VariantDraft(title="  ", body="b", changes=["c1"], level="A"))
