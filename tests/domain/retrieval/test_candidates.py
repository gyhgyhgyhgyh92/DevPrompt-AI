"""F-102 候选检索测试：打分、截断、来源、降级、中英映射扩展。"""

from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.candidates import (
    MAX_CANDIDATES,
    MIN_CANDIDATES,
    ZH_EN_MAP,
    build_candidates,
    expand_zh_en,
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
    # 分词规则（3B 冻结）：中文二元组与英文词元不相交，path 通道需原句含路径英文词。
    # 断言调整理由：中英映射加入 页面→page 后原句「页面」会命中 renderPage 符号名，
    # source 正确翻转为 symbol；本用例意图是验证 path 通道标注，故改用仅命中
    # 路径词元（user/center）且不触碰符号名词元（render/page）的原句。
    syms = [_sym("renderPage", "src/user/center/page.tsx")]
    result = build_candidates("调整 user center 的间距样式", syms)
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


# ── expand_zh_en：滑动窗口匹配（先 3 字窗再 2 字窗，命中即消费） ──


def test_expand_three_char_window_priority() -> None:
    # 购物车 命中 3 字窗整体消费，不产生 购物/物车 中间碎片
    assert expand_zh_en("购物车") == ["cart"]


def test_expand_two_char_window() -> None:
    assert expand_zh_en("提交按钮") == ["submit", "button"]


def test_expand_no_mapping_returns_empty() -> None:
    # 无映射词与单字（key 最短 2 字）均不产出词元
    assert expand_zh_en("给xyz的备注说明") == []


def test_expand_mixed_sentence_skips_non_cjk() -> None:
    # 中英混排：只处理 CJK 连续段，英文与数字原样留给 tokenize_sentence
    assert expand_zh_en("把 提交按钮 的 primary-500 背景改掉") == [
        "submit",
        "button",
        "background",
    ]


def test_expand_dedup_preserves_order() -> None:
    # 价格→price 与 金额→price 同词元，整句去重保序
    assert expand_zh_en("价格金额") == ["price"]


def test_expand_window_consumes_then_continues() -> None:
    # 搜索框 消费 3 字窗后从窗尾继续，后续 搜索 仍独立命中（search 去重只留一次）
    assert expand_zh_en("搜索框和搜索") == ["search", "box"]


def test_expand_multivalue_splits_and_lowercases() -> None:
    # value 可含空格分隔多词元；命令→command cmd 两个词元都产出
    assert expand_zh_en("命令") == ["command", "cmd"]


def test_expand_map_quality_constraints() -> None:
    # 词表质量：key 为 2~3 字纯中文（与英文词元空间无冲突），value 为非空小写英文词元
    assert len(ZH_EN_MAP) >= 150
    for key, value in ZH_EN_MAP.items():
        assert 2 <= len(key) <= 3
        assert not any(ch.isascii() for ch in key)
        tokens = value.split()
        assert tokens
        assert all(t == t.lower() and t.isalpha() for t in tokens)


# ── build_candidates 集成：映射注入后纯中文句子可命中 ──


def test_zh_sentence_hits_symbol_source() -> None:
    syms = [_sym("SubmitButton", "src/components.tsx")]
    result = build_candidates("提交按钮默认背景色改为 primary-500", syms)
    assert result.candidates[0].name == "SubmitButton"
    assert result.candidates[0].source == "symbol"


def test_zh_sentence_ranks_by_term_overlap() -> None:
    # 用户表格 命中 user+table（4 分），高于仅 button 命中的 SubmitButton（2 分）
    syms = [_sym("UserTable", "src/components.tsx"), _sym("SubmitButton", "src/components.tsx")]
    result = build_candidates("给用户表格的操作列加一个删除按钮", syms)
    assert result.candidates[0].name == "UserTable"
    assert result.candidates[0].source == "symbol"


def test_zh_sentence_intentional_miss_stays_miss() -> None:
    # 全局搜索框：语料无 SearchBox 时不得凭空命中；零重叠触发人工指定
    syms = [_sym("UserTable", "src/components.tsx"), _sym("LoginForm", "src/components.tsx")]
    result = build_candidates("首页顶部加一个全局搜索框", syms)
    assert all(c.name != "SearchBox" for c in result.candidates)
    assert result.candidates == []
    assert result.manual_required is True


def test_zh_sentence_hits_via_path_tokens() -> None:
    # 日期格式化 → date+format，formatDate 符号名命中；符号名命中优先标 symbol
    syms = [_sym("formatDate", "src/index.ts")]
    result = build_candidates("日期格式化加相对时间显示", syms)
    assert result.candidates[0].name == "formatDate"
    assert result.candidates[0].source == "symbol"
