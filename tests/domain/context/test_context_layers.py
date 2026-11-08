"""四层提示与契约测试：分类、增量、尾部锚点、账本与摘要后检。"""

from __future__ import annotations

from devprompt_ai.domain.context.build_context import TurnInput, build_context
from devprompt_ai.domain.context.ledger import LedgerInput, build_ledger, quantize
from devprompt_ai.domain.context.prompt_layers import (
    assert_append_only,
    render_context_full,
    render_delta,
)
from devprompt_ai.domain.context.summary import build_summary_prompt, choose_summary
from devprompt_ai.domain.context.task_contract import (
    ContractStatus,
    TaskContract,
    TurnMode,
    classify_turn_mode,
    extract_contract,
    merge_followup,
    render_tail_anchor,
)
from devprompt_ai.domain.prompt_guard import (
    DELIVERY_CONTRACT,
    EVIDENCE_SCOPE,
    EXTERNAL_SOURCE_VERIFICATION,
    family_note,
)


def test_classify_chat_follow_up_and_task() -> None:
    assert classify_turn_mode("你好", has_contract=False) is TurnMode.CHAT
    assert classify_turn_mode("继续做下一个", has_contract=True) is TurnMode.FOLLOW_UP
    assert classify_turn_mode("把导出按钮加上", has_contract=False) is TurnMode.TASK


def test_extract_contract_pulls_scope_and_constraints() -> None:
    contract = extract_contract("把 src/ui/Button.tsx 的导出加上，不要改样式", 2)

    assert "导出" in contract.objective
    assert "src/ui/Button.tsx" in contract.scope_paths
    assert any("不要改样式" in item for item in contract.constraints)
    assert contract.created_at_turn == 2


def test_merge_followup_never_rewrites_objective() -> None:
    contract = extract_contract("把导出按钮加上", 0)
    merged = merge_followup(contract, "继续，范围也包括 src/ui/Icon.tsx", turn_index=1)

    assert merged.objective == contract.objective
    assert "src/ui/Icon.tsx" in merged.scope_paths
    assert merged.updated_at_turn == 1


def test_tail_anchor_declares_authority() -> None:
    contract = extract_contract("把导出按钮加上", 0)
    anchored = render_tail_anchor(contract, completed=("定位目标",), remaining=("补测试",))

    assert 'authoritative="true"' in anchored
    assert "以本块为准" in anchored
    assert "把导出按钮加上" in anchored
    assert "补测试" in anchored


def test_render_full_and_delta() -> None:
    previous = {"project_memory": "a", "working_set": "b"}
    full = render_context_full(previous, seq=1)
    assert 'mode="full"' in full and "<project_memory>" in full

    delta = render_delta(previous, {"project_memory": "a", "working_set": "c"}, seq=2)
    assert 'mode="delta"' in delta
    assert "working_set" in delta
    assert "project_memory" not in delta, "未变化的块不得重发"


def test_delta_without_changes_is_self_closing() -> None:
    context = {"project_memory": "a"}
    delta = render_delta(context, dict(context), seq=3)

    assert delta == '<context-update seq="3"/>'


def test_append_only_guard() -> None:
    assert assert_append_only([1, 2], [1, 2, 3]) is True
    assert assert_append_only([1, 2], [1, 9, 3]) is False
    assert assert_append_only([1, 2], [1]) is False


def test_build_context_inserts_delta_before_ledger_and_anchor() -> None:
    payload = build_context(
        [],
        TurnInput(sentence="加导出"),
        ledger_block="【账本】",
        delta_block='<context-update seq="2"/>',
        tail_anchor="【权威块】",
    )

    text = payload.history_block
    assert text.index("context-update") < text.index("【账本】") < text.index("【权威块】")


def test_ledger_is_stable_and_quantized() -> None:
    assert quantize(0.1) == "low"
    assert quantize(0.5) == "mid"
    assert quantize(0.9) == "high"

    data = LedgerInput(
        contract=TaskContract(objective="加导出", status=ContractStatus.EXECUTING),
        turn_index=3,
        files_modified=4,
        verified=3,
        sensorium_score=0.8,
        trace=("retrieve", "probe", "generate"),
    )
    first = build_ledger(data)
    second = build_ledger(data)

    assert first == second, "同一状态必须字节稳定"
    assert "3/4" in first and "high" in first


def test_prompt_discipline_constants_and_family_notes() -> None:
    assert EVIDENCE_SCOPE and EXTERNAL_SOURCE_VERIFICATION and DELIVERY_CONTRACT
    assert family_note("DeepSeek") != ""
    assert family_note("unknown-vendor") == ""


def test_summary_postcheck_falls_back_on_missing_state() -> None:
    fallback = "## 用户核心需求\n加导出"

    assert choose_summary(None, required=[], fallback=fallback) == (fallback, True)
    assert choose_summary("空摘要", required=["导出"], fallback=fallback) == (fallback, True)
    assert choose_summary("我们决定加导出", required=["导出"], fallback=fallback) == (
        "我们决定加导出",
        False,
    )


def test_summary_prompt_requests_lossless_merge() -> None:
    system, user = build_summary_prompt("历史", previous="旧摘要")

    assert "必须完整保留" in system
    assert "无损合并" in user
