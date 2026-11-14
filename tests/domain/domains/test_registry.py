"""领域包注册表与契约测试：包完整性、动作白名单、断言 kinds、i18n 键齐全性。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from devprompt_ai.common.i18n import Locale, tr
from devprompt_ai.domain.agent.action import TERMINAL_ACTIONS, AgentAction
from devprompt_ai.domain.domains import (
    KNOWN_DOMAIN_IDS,
    DomainVerdict,
    all_packs,
    get_pack,
)
from devprompt_ai.domain.domains.registry import _PACKS
from devprompt_ai.domain.generate.claims import _KIND_FACT


def test_all_packs_registered_in_known_order() -> None:
    packs = all_packs()
    assert [p.id for p in packs] == list(KNOWN_DOMAIN_IDS)
    assert set(_PACKS) == set(KNOWN_DOMAIN_IDS)


@pytest.mark.parametrize("domain", KNOWN_DOMAIN_IDS)
def test_get_pack_roundtrip(domain: str) -> None:
    pack = get_pack(domain)
    assert pack.id == domain
    assert pack.keywords, "词表为空则确定性路由永远不命中"
    assert pack.name_key == f"domain.{domain}.name"


def test_get_pack_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        get_pack("unknown")


def test_code_pack_uses_full_repo_pipeline() -> None:
    pack = get_pack("code")
    assert pack.needs_repo is True
    assert pack.allowed_actions == frozenset(AgentAction)
    # 断言 kinds 必须都能在 claims 的核对表中找到（防止模板声明无法核验的 kind）
    assert pack.claim_kinds <= frozenset(_KIND_FACT)
    assert "test" in pack.claim_kinds


@pytest.mark.parametrize("domain", [d for d in KNOWN_DOMAIN_IDS if d != "code"])
def test_generic_packs_bypass_repo(domain: str) -> None:
    pack = get_pack(domain)
    assert pack.needs_repo is False
    # 通用包剔除仓库动作，保留提问/生成/交付骨架（含终结动作，循环可收尾）
    assert AgentAction.RETRIEVE not in pack.allowed_actions
    assert AgentAction.PROBE not in pack.allowed_actions
    assert AgentAction.DELEGATE not in pack.allowed_actions
    assert {AgentAction.ASK, AgentAction.DELIVER} <= pack.allowed_actions
    assert pack.allowed_actions >= TERMINAL_ACTIONS
    # 无仓库证据 → 断言 kinds 为空，交付门走结构化校验
    assert pack.claim_kinds == frozenset()


@pytest.mark.parametrize(
    ("domain", "extra_directives"),
    [("code", False), *[(d, True) for d in KNOWN_DOMAIN_IDS if d != "code"]],
)
@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_pack_i18n_keys_resolvable(domain: str, extra_directives: bool, locale: Locale) -> None:
    pack = get_pack(domain)
    assert tr(pack.name_key, locale) != pack.name_key
    if extra_directives:
        assert pack.directives_key != ""
        assert tr(pack.directives_key, locale) != pack.directives_key
    else:
        assert pack.directives_key == ""
    assert tr(pack.sections_key, locale) != pack.sections_key


def test_verdict_serialization_roundtrip() -> None:
    verdict = DomainVerdict(domain="work", source="keyword", confidence=0.9)
    data = verdict.model_dump()
    assert DomainVerdict.model_validate(data) == verdict


def test_verdict_rejects_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        DomainVerdict(domain="code", source="llm", confidence=1.5)
