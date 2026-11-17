"""J3–J5 注入测试：三条提示条款必须真的进了 system prompt。"""

from __future__ import annotations

from devprompt_ai.config import AppConfig
from devprompt_ai.decision import prompts
from devprompt_ai.domain.prompt_guard import (
    DELIVERY_CONTRACT,
    EVIDENCE_SCOPE,
    EXTERNAL_SOURCE_VERIFICATION,
    family_note,
)
from devprompt_ai.harness.llm import _instructions


def test_facts_prompt_contains_evidence_scope_and_external_source() -> None:
    assert EVIDENCE_SCOPE in prompts.FACTS_SYSTEM
    assert EXTERNAL_SOURCE_VERIFICATION in prompts.FACTS_SYSTEM


def test_next_action_prompt_contains_delivery_contract() -> None:
    assert DELIVERY_CONTRACT in prompts.NEXT_ACTION_SYSTEM


def test_family_note_enters_system_only_for_known_vendor() -> None:
    deepseek = _instructions(AppConfig(llm_provider="deepseek"), "BASE", "{}")
    unknown = _instructions(AppConfig(llm_provider="unknown-vendor"), "BASE", "{}")

    assert family_note("deepseek") in deepseek
    assert unknown.startswith("BASE\n\n"), "未知厂商不得插入校准语句"


def test_clauses_are_not_empty() -> None:
    assert len(EVIDENCE_SCOPE) > 10
    assert len(EXTERNAL_SOURCE_VERIFICATION) > 10
    assert len(DELIVERY_CONTRACT) > 10
