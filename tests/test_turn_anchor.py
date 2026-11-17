"""TurnAnchor 纯函数测试：抽取 / 追加合并 / 渲染稳定 / 畸形 payload。"""

from __future__ import annotations

from devprompt_ai.domain.agent.anchor import (
    TurnAnchor,
    anchor_from_payload,
    anchor_to_payload,
    extract_anchor,
    merge_followup,
    render_anchor,
)


def test_extract_strips_greeting_and_keeps_first_sentence() -> None:
    anchor = extract_anchor("帮我 把提交按钮改成主色。顺便补个导出。", 2)

    assert anchor.objective == "把提交按钮改成主色"
    assert anchor.created_at_turn == 2
    assert anchor.updated_at_turn == 2


def test_extract_objective_falls_back_to_raw_when_only_greeting() -> None:
    anchor = extract_anchor("帮我", 0)

    assert anchor.objective == "帮我"


def test_extract_paths_normalizes_separators_and_dot_prefix() -> None:
    anchor = extract_anchor(r"改 src\components\Submit.tsx 和 ./src/a/b.vue 里的按钮", 0)

    assert anchor.scope_paths == ("src/components/Submit.tsx", "src/a/b.vue")


def test_extract_constraints_only_hits_real_constraint_clauses() -> None:
    anchor = extract_anchor("改按钮颜色，不要动布局。这两个的区别是什么？必须补测试。", 0)

    assert anchor.constraints == ("改按钮颜色，不要动布局", "必须补测试")


def test_merge_followup_appends_without_rewriting_objective() -> None:
    base = extract_anchor("把提交按钮改成主色", 1)
    merged = merge_followup(base, "还有 src/Panel.vue 也要一起改，不要动其它页面", turn_index=2)

    assert merged is not base
    assert merged.objective == "把提交按钮改成主色"
    assert merged.scope_paths == ("src/Panel.vue",)
    assert merged.constraints == ("还有 src/Panel.vue 也要一起改，不要动其它页面",)
    assert merged.created_at_turn == 1
    assert merged.updated_at_turn == 2


def test_merge_followup_returns_same_object_when_nothing_new() -> None:
    base = extract_anchor("把提交按钮改成主色", 1)

    assert merge_followup(base, "再换个说法", turn_index=2) is base


def test_merge_followup_does_not_duplicate_existing_items() -> None:
    base = extract_anchor("改 src/A.tsx，不要动布局", 0)
    merged = merge_followup(base, "改 src/A.tsx，不要动布局", turn_index=1)

    assert merged is base
    assert merged.scope_paths == ("src/A.tsx",)


def test_render_is_stable_and_bounded() -> None:
    anchor = extract_anchor("把提交按钮改成主色", 0)

    first = render_anchor(anchor)
    assert first == render_anchor(anchor)
    assert "【本轮目标】" in first
    assert "【成功标准】" in first
    assert len(first) <= 300


def test_render_returns_empty_for_empty_objective() -> None:
    assert render_anchor(TurnAnchor(objective="")) == ""


def test_anchor_payload_roundtrip() -> None:
    anchor = extract_anchor("改 src/A.tsx，必须保持兼容", 3)

    restored = anchor_from_payload(anchor_to_payload(anchor))

    assert restored == anchor


def test_anchor_from_payload_rejects_malformed() -> None:
    assert anchor_from_payload(None) is None
    assert anchor_from_payload([]) is None
    assert anchor_from_payload({}) is None
    assert anchor_from_payload({"objective": ""}) is None
    assert anchor_from_payload({"objective": 123}) is None


def test_anchor_from_payload_tolerates_partial_fields() -> None:
    anchor = anchor_from_payload({"objective": "改按钮", "scope_paths": "not-a-list"})

    assert anchor is not None
    assert anchor.objective == "改按钮"
    assert anchor.scope_paths == ()
    assert anchor.success_criteria  # 缺省回落到默认两条
