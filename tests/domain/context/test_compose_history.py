"""B13/B15 拼接顺序测试：历史 → 账本 → 权威锚点。"""

from __future__ import annotations

from devprompt_ai.domain.context.build_context import compose_history


def test_order_is_history_ledger_anchor() -> None:
    composed = compose_history("历史", ledger="账本", anchor="锚点")

    assert composed == "历史\n\n账本\n\n锚点"


def test_empty_blocks_are_skipped() -> None:
    assert compose_history("历史") == "历史"
    assert compose_history("", ledger="账户") == "账户"
    assert compose_history("", ledger="", anchor="") == ""
    assert compose_history("历史", ledger="  ", anchor="") == "历史"


def test_anchor_is_always_last() -> None:
    composed = compose_history("历史", ledger="账本", anchor="锚点")

    assert composed.endswith("锚点"), "权威块必须在尾部，避免被摘要覆盖"
