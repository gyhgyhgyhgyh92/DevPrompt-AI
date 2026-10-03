"""common/text.py 分词规则测试。"""

from devprompt_ai.common.text import cjk_bigrams, split_identifier, tokenize_sentence


def test_split_identifier_camel_case() -> None:
    assert split_identifier("SubmitButton") == ["submit", "button"]


def test_split_identifier_consecutive_caps() -> None:
    assert split_identifier("HTTPServer") == ["http", "server"]


def test_split_identifier_snake_and_kebab() -> None:
    assert split_identifier("user_center-page") == ["user", "center", "page"]


def test_split_identifier_digits_and_path() -> None:
    assert split_identifier("src/v2/UserList.tsx") == ["src", "v2", "user", "list", "tsx"]


def test_cjk_bigrams_basic() -> None:
    assert cjk_bigrams("提交按钮") == ["提交", "交按", "按钮"]


def test_cjk_bigrams_single_char_kept() -> None:
    assert cjk_bigrams("搜") == ["搜"]


def test_cjk_bigrams_mixed_text() -> None:
    # 中文段各自切二元组，非 CJK 字符充当分隔
    assert cjk_bigrams("修改user头像") == ["修改", "头像"]


def test_tokenize_sentence_mixed() -> None:
    terms = tokenize_sentence("把用户中心页面的提交按钮背景色改为 primary-500")
    assert "提交" in terms and "按钮" in terms and "用户" in terms
    assert "primary" in terms and "500" in terms


def test_tokenize_sentence_dedup() -> None:
    # 连续 4 字段切出 [按钮, 钮按, 按钮]：重复 gram「按钮」去重保序仅留一次；
    # 「钮按」为相邻窗口的合法跨词 gram（与计划 docstring「面的」同规则），非重复项
    assert tokenize_sentence("按钮按钮") == ["按钮", "钮按"]


def test_tokenize_sentence_empty() -> None:
    assert tokenize_sentence("   ") == []


def test_tokenize_sentence_english_camel() -> None:
    # 英文 CamelCase 词拆分
    assert tokenize_sentence("fix SubmitButton style") == ["fix", "submit", "button", "style"]


def test_tokenize_sentence_pure_ascii_path() -> None:
    assert tokenize_sentence("src/components/PromptCard.tsx") == [
        "src",
        "components",
        "prompt",
        "card",
        "tsx",
    ]
