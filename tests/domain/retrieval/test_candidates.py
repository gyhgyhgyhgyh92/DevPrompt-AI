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


def test_candidates_carry_symbol_signature() -> None:
    """签名必须原样带到候选上——它就是排序阶段要的判别性上下文。"""
    syms = [
        Symbol(
            name="SubmitButton",
            path="src/ui/button.tsx",
            line=1,
            kind="function",
            signature="(props: ButtonProps)",
        )
    ]

    result = build_candidates("把提交按钮 SubmitButton 的颜色改掉", syms)

    assert result.candidates[0].signature == "(props: ButtonProps)"


def test_candidates_without_signature_keep_empty() -> None:
    """没有签名的符号 → 候选签名为空（老版 ctags 降级路径）。"""
    syms = [_sym("SubmitButton", "src/ui/button.tsx")]

    result = build_candidates("把提交按钮 SubmitButton 的颜色改掉", syms)

    assert result.candidates[0].signature == ""


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
    assert len(result.candidates) == MAX_CANDIDATES == 50  # 超限截断不报错（2026-11-15 起 50）
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
    # 词表质量：key 为 2~5 字纯中文（与英文词元空间无冲突；4~5 字为复合领域词，
    # 如 下拉列表/开发者工具，配合滑窗扩到 5→4→3→2），value 为非空小写英文词元
    assert len(ZH_EN_MAP) >= 150
    for key, value in ZH_EN_MAP.items():
        assert 2 <= len(key) <= 5
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


# ── F-801 预览缺口修复：单复数归一 / 精确名加成 / 长窗映射 / tie-break ──


def test_plural_normalization_singular_sentence_hits_plural_symbol() -> None:
    # 原句 default（默认）× 符号词元 defaults：归一后交集非空，否则零重叠
    syms = [_sym("loadDefaults", "src/config.ts")]
    result = build_candidates("加载默认值", syms)
    assert result.candidates[0].name == "loadDefaults"
    assert result.candidates[0].score == 2.0


def test_plural_normalization_plural_sentence_hits_singular_symbol() -> None:
    # 原句 cookies × 符号 Cookie：归一双侧生效，全名命中触发加成，
    # 路径词元 cookie 再叠 1 分（2+3+1=6）
    syms = [_sym("Cookie", "src/net/cookie.ts")]
    result = build_candidates("保存 cookies 到本地", syms)
    assert result.candidates[0].name == "Cookie"
    assert result.candidates[0].score == 6.0


def test_exact_name_bonus_lifts_target_above_multi_hit_competitors() -> None:
    # 同分截断场景（click-04 形态）：全名 command 命中 + 装饰器路径，
    # 压过 2 个部分词元命中的测试符号（param+default）
    syms = [
        _sym("command", "src/click/decorators.py"),
        _sym("testSharedParamPrefersFirstDefault", "tests/test_defaults.py"),
    ]
    result = build_candidates("命令装饰器支持从 yaml 读默认参数", syms)
    assert result.candidates[0].name == "command"
    assert result.candidates[0].score == 6.0
    assert result.candidates[1].score == 5.0


def test_exact_name_bonus_applies_to_normalized_plural_name() -> None:
    # 符号名 defaults 归一为 default 后与原句词元相等，加成生效
    syms = [_sym("Defaults", "src/settings.ts")]
    result = build_candidates("导出默认配置", syms)
    assert result.candidates[0].name == "Defaults"
    assert result.candidates[0].score == 5.0


def test_exact_name_bonus_requires_full_name_not_partial() -> None:
    # 部分词元命中（SubmitButton 只中 submit+button，路径无命中）不加成；
    # 全名 button 命中才加成（2+3=5）
    syms = [_sym("SubmitButton", "src/view/form.tsx"), _sym("button", "src/b.ts")]
    result = build_candidates("提交按钮 button", syms)
    by_name = {c.name: c for c in result.candidates}
    assert by_name["SubmitButton"].score == 4.0
    assert by_name["button"].score == 5.0
    assert result.candidates[0].name == "button"


def test_exact_name_bonus_not_applied_to_path_only_match() -> None:
    # path-only 候选名称必不命中 → 拿不到加成，仍是 1 分（噪声不会被打进前列）
    syms = [_sym("helper", "src/button/helper.tsx")]
    result = build_candidates("button", syms)
    assert result.candidates[0].name == "helper"
    assert result.candidates[0].score == 1.0
    assert result.candidates[0].source == "path"


def test_expand_four_char_compound_window() -> None:
    # 下拉列表（4 字复合词）→ dropdown + listbox，长窗整体消费
    assert expand_zh_en("下拉列表") == ["dropdown", "listbox"]


def test_expand_five_char_compound_window() -> None:
    # 开发者工具（5 字复合词）→ devtools
    assert expand_zh_en("开发者工具") == ["devtools"]


def test_expand_longest_window_priority() -> None:
    # 长窗优先：下拉列表整体命中后再继续处理剩余段（展开）
    assert expand_zh_en("下拉列表展开") == ["dropdown", "listbox", "expand"]


def test_new_miss_gap_mappings_bridge() -> None:
    # 27 条 MISS 推导的新映射：多值同义桥接与既有 命令→command cmd 同性质
    assert expand_zh_en("钩子分发") == ["hook", "dispatch"]
    assert expand_zh_en("水合") == ["hydrate"]
    assert expand_zh_en("热更新") == ["hmr", "hot", "update"]
    assert expand_zh_en("枚举") == ["enum", "choice"]
    assert expand_zh_en("弹窗") == ["modal", "dialog"]
    assert expand_zh_en("参数") == ["param", "argument"]
    assert expand_zh_en("状态码") == ["status"]


def test_tiebreak_prefers_more_name_hits_before_exact_bonus() -> None:
    # 同分（5.0）时先比符号名命中数（2>1），再比精确名加成——
    # 保证多词元命中目标不被单名加成群体反超（axios toFormData 形态的回归保护）
    syms = [
        _sym("UserCenter", "src/user/main.tsx"),
        _sym("user", "src/b.ts"),
    ]
    result = build_candidates("用户中心 user center", syms)
    assert result.candidates[0].name == "UserCenter"
    assert result.candidates[1].name == "user"


def test_exact_name_bonus_suppressed_for_high_df_names() -> None:
    # DF 上限：同名符号超过 _MAX_EXACT_NAME_DF 时全名加成失效——
    # 高频通名（如 click 的 cli×237）若加成会让数百同分候选霸满 25 席
    from devprompt_ai.domain.retrieval.candidates import _MAX_EXACT_NAME_DF

    syms = [_sym(f"cli_{i}", f"src/examples/e{i}.py") for i in range(_MAX_EXACT_NAME_DF)]
    syms += [_sym("cli", f"src/examples/raw{i}.py") for i in range(_MAX_EXACT_NAME_DF + 1)]
    syms.append(_sym("CliRunner", "src/click/testing.py"))
    result = build_candidates("CliRunner 混合 stdout stderr 的捕获顺序不稳定", syms)
    by_name = {c.name: c.score for c in result.candidates}
    # cli 同名群体 DF 超限：只有 2 分（1 个词元命中），不得拿到 +3 加成
    assert by_name["cli"] == 2.0
    # CliRunner 两个词元命中 4 分，压过 cli 群体排第一
    assert by_name["CliRunner"] == 4.0
    assert result.candidates[0].name == "CliRunner"


def test_exact_name_bonus_applies_at_df_cap_boundary() -> None:
    # 边界：DF 恰好等于上限时加成仍生效（≤ 判定）
    from devprompt_ai.domain.retrieval.candidates import _MAX_EXACT_NAME_DF

    syms = [_sym("mount", f"src/a{i}.py") for i in range(_MAX_EXACT_NAME_DF)]
    result = build_candidates("mount 挂载适配器的前缀匹配支持通配符", syms)
    assert all(c.score == 5.0 for c in result.candidates)  # 2 + 3 加成


def test_generic_ui_term_does_not_take_exact_bonus() -> None:
    """真实回归（2026-11-15）：中文「页面」译成 page 后不得靠 +3 压过业务目标。

    实测原句「前端页面中的管理员界面的新增图书按钮改为红色」曾把后端 Java 的
    page 符号顶到 7.0，而真正目标 BookListPage 只有 6.0。
    """
    syms = [
        _sym("page", "task-back/src/main/java/com/example/book/common/PageResult.java"),
        _sym("page", "task-front/src/pages/borrow/AvailableBooksPage.tsx"),
        _sym("BookAddDTO", "task-back/src/main/java/com/example/book/dto/BookAddDTO.java"),
        _sym("BookListPage", "task-front/src/pages/bookManage/BookListPage.tsx"),
    ]

    result = build_candidates("将当前项目中的前端页面中的管理员界面中的新增图书按钮改为红色", syms)

    # page 只拿到名字 2 分 + 路径 2 分，精确名加成被泛词豁免
    assert all(c.score == 4.0 for c in result.candidates if c.name == "page")
    # 前端业务符号排首位（同分时技术栈优先）
    assert result.candidates[0].name == "BookListPage"
    assert result.candidates[0].path.endswith("BookListPage.tsx")


def test_literal_english_term_still_takes_exact_bonus() -> None:
    """用户字面写了英文词时，精确名加成语义不变（比只靠中文映射多 3 分）。"""
    syms = [_sym("button", "src/ui/button.tsx")]

    with_word = build_candidates("把提交按钮 button 的颜色改掉", syms)
    without = build_candidates("把提交按钮的颜色改掉", syms)

    assert with_word.candidates[0].score - without.candidates[0].score == 3.0


#: 泛词集合的维护契约：这些中文键的译词必须都在 _GENERIC_UI_TERMS 里。
#: 新增/修改 UI 映射时漏登记会让本测试失败——这就是「词表与泛词集合漂移」的闸门。
_UI_ZH_KEYS = (
    "按钮",
    "输入",
    "输入框",
    "表单",
    "表格",
    "列表",
    "弹窗",
    "对话框",
    "提示",
    "标签",
    "标签页",
    "菜单",
    "导航",
    "面包屑",
    "分页",
    "头像",
    "徽标",
    "骨架",
    "骨架屏",
    "占位",
    "通知",
    "消息",
    "搜索框",
    "下拉",
    "复选",
    "单选",
    "开关",
    "滑块",
    "进度",
    "抽屉",
    "气泡",
    "轮播",
    "遮罩",
    "悬停",
    "点击",
    "选中",
    "禁用",
    "启用",
    "只读",
    "高亮",
    "边框",
    "圆角",
    "阴影",
    "间距",
    "宽度",
    "高度",
    "尺寸",
    "布局",
    "样式",
    "主题",
    "字体",
    "行高",
    "透明度",
    "动画",
    "过渡",
    "响应式",
    "适配",
    "页面",
    "界面",
    "首页",
    "视图",
    "组件",
    "模块",
    "应用",
    "入口",
    "侧边栏",
    "工具栏",
    "页头",
    "页脚",
    "斑马纹",
)


def test_generic_ui_terms_stay_in_sync_with_ui_mappings() -> None:
    """漂移闸门：UI 词表改了就同步泛词集合，否则 page/button 类误判会复发。"""
    from devprompt_ai.domain.retrieval.candidates import _GENERIC_UI_TERMS

    for key in _UI_ZH_KEYS:
        assert key in ZH_EN_MAP, f"UI 键 {key!r} 不在 ZH_EN_MAP"
        for word in ZH_EN_MAP[key].split():
            assert word in _GENERIC_UI_TERMS, f"{key} → {word!r} 未登记为泛词"


def test_unknown_suffix_does_not_take_stack_preference() -> None:
    """未列入白名单的语言（如 .md）不参与偏好，退化为原行为（按名字长度/路径）。"""
    syms = [
        _sym("Book", "docs/book/Book.md"),
        _sym("Book", "task-front/src/book/Book.tsx"),
    ]

    result = build_candidates("前端页面里把图书 Book 的标题改一下", syms)

    # 前端 .tsx 仍优先；.md 不因偏好被误判成后端而额外受益
    assert result.candidates[0].path.endswith(".tsx")


def test_stack_preference_is_tiebreak_only() -> None:
    """技术栈只作同分档位：分数完全不受影响，跨端同分时才分先后。"""
    syms = [
        _sym("Book", "task-back/src/book/Book.java"),
        _sym("Book", "task-front/src/book/Book.tsx"),
    ]

    front = build_candidates("前端页面里把图书 Book 的标题改一下", syms)
    back = build_candidates("后端接口里把图书 Book 的实体改一下", syms)

    assert {c.score for c in front.candidates} == {6.0}  # 名字 2 + 路径 1 + 加成 3
    assert front.candidates[0].path.endswith(".tsx")
    assert back.candidates[0].path.endswith(".java")
