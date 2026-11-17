"""确定性关键词路由测试：命中、大小写、未命中、词表冲突先到先得。"""

from __future__ import annotations

from devprompt_ai.domain.domains.rules import KEYWORD_CONFIDENCE, match_by_keyword


def test_work_keyword_hits() -> None:
    assert match_by_keyword("帮我写个周报，重点写数据") == ("work", KEYWORD_CONFIDENCE)


def test_life_keyword_hits() -> None:
    hit = match_by_keyword("国庆去成都玩，帮我做份行程")
    assert hit is not None
    assert hit[0] == "life"


def test_creative_keyword_hits() -> None:
    hit = match_by_keyword("给新款奶茶想一句广告语")
    assert hit is not None
    assert hit[0] == "creative"


def test_english_keyword_casefold() -> None:
    hit = match_by_keyword("Fix the login BUG in auth module")
    assert hit is not None
    assert hit[0] == "code"


def test_no_keyword_returns_none() -> None:
    # 「帮我整理一下」无任何领域词 → 交由 LLM 分类/继承
    assert match_by_keyword("帮我整理一下") is None


def test_first_registered_pack_wins_on_overlap() -> None:
    # 「接口」在 code 词表；「方案」在 work 词表——同一句同时命中两包时按注册顺序
    hit = match_by_keyword("写个接口设计方案")
    assert hit is not None
    assert hit[0] == "code"
