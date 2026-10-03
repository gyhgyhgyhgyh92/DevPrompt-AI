"""F-102 候选检索测试：打分、截断、来源、降级。"""

from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.candidates import (
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    build_candidates,
)


def _sym(name: str, path: str, kind: str = "function") -> Symbol:
    from typing import cast

    from devprompt_ai.domain.models import SymbolKind

    return Symbol(name=name, path=path, line=1, kind=cast(SymbolKind, kind))


def test_exact_symbol_match_ranks_first() -> None:
    syms = [_sym("SubmitButton", "src/ui/button.tsx"), _sym("UserList", "src/user/list.tsx")]
    result = build_candidates("把提交按钮 SubmitButton 的颜色改掉", syms)
    assert result.candidates[0].name == "SubmitButton"
    assert result.candidates[0].source == "symbol"


def test_path_match_marks_source_path() -> None:
    # 分词规则（3B 冻结）：中文二元组与英文词元不相交，path 通道需原句含路径英文词
    syms = [_sym("renderPage", "src/user/center/page.tsx")]
    result = build_candidates("调整 user center 页面的样式", syms)
    assert result.candidates[0].name == "renderPage"
    assert result.candidates[0].source == "path"


def test_hard_limit_25_truncates() -> None:
    # comp_{i} 经 split_identifier 拆出独立词元 "comp"（Comp{i} 会合成 comp0 而无法命中）
    syms = [_sym(f"comp_{i}", f"src/c{i}.tsx") for i in range(60)]
    syms.append(_sym("SubmitButton", "src/ui/button.tsx"))
    # 原句命中 SubmitButton + 每个 comp_{i} 含 "comp" 词元
    result = build_candidates("submit button comp", syms)
    assert len(result.candidates) == MAX_CANDIDATES == 25  # 超限截断不报错（MUST-09）
    assert result.candidates[0].name == "SubmitButton"  # 按匹配度截断：高分在前


def test_no_code_body_in_candidates() -> None:
    syms = [_sym("SubmitButton", "src/ui/button.tsx")]
    result = build_candidates("提交按钮", syms)
    payload = repr(result.candidates)
    # MUST-09：候选集仅符号名+路径；类型层无正文字段，序列化亦不得含正文
    assert "body" not in payload and "content" not in payload


def test_below_min_triggers_manual() -> None:
    syms = [_sym("Unrelated", "src/x.py")]
    result = build_candidates("完全没有关系的说法", syms)
    assert len(result.candidates) < MIN_CANDIDATES
    assert result.manual_required is True


def test_at_or_above_min_no_manual() -> None:
    syms = [
        _sym("UserCenter", "src/user/center.tsx"),
        _sym("CenterPanel", "src/user/panel.tsx"),
        _sym("UserAvatar", "src/user/avatar.tsx"),
    ]
    result = build_candidates("调整 user center 页面", syms)
    assert result.manual_required is False


def test_empty_sentence_manual() -> None:
    result = build_candidates("   ", [_sym("A", "a.py")])
    assert result.manual_required is True


def test_empty_symbols_manual() -> None:
    result = build_candidates("提交按钮", [])
    assert result.candidates == []
    assert result.manual_required is True


def test_score_ordering_desc() -> None:
    syms = [_sym("Button", "src/button.tsx"), _sym("SubmitButton", "src/ui/submit/button.tsx")]
    result = build_candidates("提交按钮 submit button", syms)
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
