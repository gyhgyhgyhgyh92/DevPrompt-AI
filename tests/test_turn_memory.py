"""跨轮继承契约（domain/agent/memory）纯函数测试。

覆盖：空原句沿用、指纹判定（含缺失即失效的 fail-safe）、序列化往返、
畸形 payload 的防御性解析、方案套数上限。
"""

from devprompt_ai.domain.agent.memory import MAX_INHERITED_VARIANTS, TurnMemory
from devprompt_ai.domain.generate.ports import Level, VariantDraft
from devprompt_ai.domain.models import FactKey, FactResult

#: 七项事实键的取样（FactResult.key 受 Literal 约束，越界键会被 from_payload 丢弃）
_FACT_KEYS_SAMPLE: list[FactKey] = [
    "target_file_exists",
    "symbol_in_file",
    "token_defined",
    "has_data_testid",
    "has_state_styles",
    "file_type_matches",
    "test_file_exists",
]


def facts_of(*passed: bool) -> tuple[FactResult, ...]:
    return tuple(
        FactResult(key=_FACT_KEYS_SAMPLE[i], passed=value, evidence=f"ev{i}")
        for i, value in enumerate(passed)
    )


def variants_of(count: int) -> tuple[VariantDraft, ...]:
    levels: list[Level] = ["A", "B", "C", "A"]
    return tuple(
        VariantDraft(title=f"t{i}", body=f"b{i}", changes=[], level=levels[i % 4])
        for i in range(count)
    )


def test_inherit_keeps_clarifications_for_same_target() -> None:
    """跨轮继承已确认的问答：零基础用户不该被重复问同一件事。"""
    memory = TurnMemory(
        sentence="给按钮加 loading 态",
        clarifications={"改哪个页面": "列表页"},
        target={"name": "SubmitButton", "path": "src/ui/button.tsx"},
    )

    inherited = memory.inherit_for_next_turn("再改一下颜色")

    assert inherited.clarifications == {"改哪个页面": "列表页"}
    assert inherited.target == {"name": "SubmitButton", "path": "src/ui/button.tsx"}


def test_inherit_keeps_previous_sentence_when_new_one_is_blank() -> None:
    memory = TurnMemory(sentence="给按钮加 loading 态", facts=facts_of(True))

    inherited = memory.inherit_for_next_turn("   ")

    assert inherited.sentence == "给按钮加 loading 态"


def test_inherit_uses_new_sentence_when_provided() -> None:
    memory = TurnMemory(sentence="旧目标")

    assert memory.inherit_for_next_turn("B 档第 2 条改成 X").sentence == "B 档第 2 条改成 X"


def test_inherit_carries_variants_and_facts_but_not_clarifications() -> None:
    memory = TurnMemory(
        sentence="目标",
        facts=facts_of(True, False),
        facts_mtime_digest="d1",
        variants=variants_of(3),
        clarifications={"范围?": "仅按钮"},
    )

    inherited = memory.inherit_for_next_turn("再改一处")

    assert len(inherited.variants) == 3
    assert len(inherited.facts) == 2
    assert inherited.facts_mtime_digest == "d1"
    # 2026-11-05：澄清改为跨轮继承（目标变了由 service 层作废）
    assert inherited.clarifications == {"范围?": "仅按钮"}


def test_inherit_caps_variant_count() -> None:
    memory = TurnMemory(variants=variants_of(MAX_INHERITED_VARIANTS + 1))

    assert len(memory.inherit_for_next_turn("x").variants) == MAX_INHERITED_VARIANTS


def test_is_stale_detects_digest_change() -> None:
    memory = TurnMemory(facts=facts_of(True), facts_mtime_digest="digest-a")

    assert memory.is_stale("digest-a") is False
    assert memory.is_stale("digest-b") is True


def test_is_stale_fails_safe_when_either_digest_missing() -> None:
    with_digest = TurnMemory(facts=facts_of(True), facts_mtime_digest="digest-a")
    without_digest = TurnMemory(facts=facts_of(True), facts_mtime_digest="")

    assert with_digest.is_stale("") is True
    assert without_digest.is_stale("digest-a") is True


def test_no_facts_is_never_stale() -> None:
    """没有继承取证时不存在过期问题，不该触发重取。"""
    assert TurnMemory(facts_mtime_digest="").is_stale("anything") is False


def test_payload_roundtrip() -> None:
    memory = TurnMemory(
        sentence="目标",
        facts=facts_of(True, False),
        facts_mtime_digest="digest-a",
        variants=variants_of(2),
        clarifications={"范围?": "仅按钮"},
    )

    restored = TurnMemory.from_payload(memory.to_payload())

    assert restored.sentence == memory.sentence
    assert [f.key for f in restored.facts] == [f.key for f in memory.facts]
    assert restored.facts_mtime_digest == "digest-a"
    assert [v.level for v in restored.variants] == ["A", "B"]
    assert restored.clarifications == {"范围?": "仅按钮"}


def test_from_payload_tolerates_malformed_input() -> None:
    assert TurnMemory.from_payload(None) == TurnMemory()
    assert TurnMemory.from_payload("nope") == TurnMemory()

    dirty = {
        "sentence": 123,
        "facts": [
            {"key": "symbol_in_file", "passed": True, "evidence": "e"},
            {"key": "not_a_fact_key", "passed": True},
            {"key": 1},
            "junk",
        ],
        "variants": [{"title": "t", "body": "b", "level": "A"}, {"broken": True}],
        "clarifications": {"q": 1},
    }
    restored = TurnMemory.from_payload(dirty)

    assert restored.sentence == "123"
    assert len(restored.facts) == 1
    assert len(restored.variants) == 1
    assert restored.clarifications == {"q": "1"}
