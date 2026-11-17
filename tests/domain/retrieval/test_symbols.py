"""F-101 纯函数测试：ctags JSON 解析 + 缓存键（无 I/O，MUST-06 验证标准）。"""

from devprompt_ai.domain.retrieval.symbols import (
    EXCLUDED_DIRS,
    SIGNATURE_LIMIT,
    build_ctags_args,
    cache_key,
    parse_ctags_output,
)


def test_parse_ctags_json_lines() -> None:
    raw = "\n".join(
        [
            '{"_type":"tag","name":"PromptCard","path":"src/ui/PromptCard.tsx","line":12,"kind":"function"}',
            '{"_type":"ptag","name":"_ctags_version","value":"6.1.0"}',  # 非 tag 行跳过
            '{"_type":"tag","name":"SubmitButton","path":"src/ui/button.tsx","line":30,"kind":"class"}',
            "not-json-line",  # 脏行跳过
        ]
    )
    symbols = parse_ctags_output(raw)
    assert len(symbols) == 2
    assert symbols[0].name == "PromptCard"
    assert symbols[0].path == "src/ui/PromptCard.tsx"  # POSIX 归一化
    assert symbols[0].line == 12
    assert symbols[0].kind == "function"
    assert symbols[1].kind == "class"


def test_parse_ctags_kind_mapping() -> None:
    raw = "\n".join(
        [
            '{"_type":"tag","name":"a","path":"a.py","line":1,"kind":"member"}',
            '{"_type":"tag","name":"b","path":"b.py","line":1,"kind":"interface"}',
            '{"_type":"tag","name":"c","path":"c.py","line":1,"kind":"macro"}',
        ]
    )
    by_name = {s.name: s.kind for s in parse_ctags_output(raw)}
    assert by_name["a"] == "variable"  # member → variable
    assert by_name["b"] == "class"  # interface → class
    assert by_name["c"] == "other"


def test_parse_ctags_empty_and_dirty() -> None:
    assert parse_ctags_output("") == []
    assert parse_ctags_output("garbage\n\n") == []


def test_parse_ctags_posix_path_normalized() -> None:
    # ctags 在 Windows 可能输出反斜杠与 ./ 前缀，解析层统一为 POSIX 相对形式
    raw = '{"_type":"tag","name":"a","path":".\\\\src\\\\ui\\\\a.tsx","line":3,"kind":"function"}'
    symbols = parse_ctags_output(raw)
    assert symbols[0].path == "src/ui/a.tsx"


def test_parse_ctags_missing_fields_skipped() -> None:
    raw = "\n".join(
        [
            '{"_type":"tag","name":"","path":"a.py","line":1,"kind":"function"}',  # 空名跳过
            '{"_type":"tag","name":"x","path":"","line":1,"kind":"function"}',  # 空路径跳过
            '{"_type":"tag","name":"y","path":"y.py","line":"3"}',  # 行号非 int 跳过
            '{"_type":"tag","name":"ok","path":"ok.py","line":9,"kind":"function"}',
        ]
    )
    symbols = parse_ctags_output(raw)
    assert [s.name for s in symbols] == ["ok"]


def test_build_ctags_args_contains_excludes_and_root() -> None:
    args = build_ctags_args("C:/proj")
    assert args[0] == "ctags"
    assert "--output-format=json" in args
    # 签名是排序阶段唯一缺失的判别性上下文（W3 实测归因）
    assert "--fields=+n+{signature}" in args
    # ctags 6.1.0 默认不映射 .tsx（实测零 tag），必须显式补映射
    assert "--map-TypeScript=+.tsx" in args
    # md 标题会混入符号表污染候选名额，保持符号表 = 纯代码符号
    assert "--languages=-Markdown" in args
    assert args[-1] == "C:/proj"
    for d in EXCLUDED_DIRS:
        assert f"--exclude={d}" in args


def test_build_ctags_args_can_drop_signature_for_old_ctags() -> None:
    """老版 ctags 不认 {signature} → 降级参数必须可构造（harness 侧据此重试）。"""
    args = build_ctags_args("C:/proj", with_signature=False)

    assert "--fields=+n" in args
    assert "--fields=+n+{signature}" not in args


def test_parse_ctags_output_reads_signature() -> None:
    """签名取首行并压空白——它要作为一行可读的判别信息给决策层看。"""
    raw = (
        '{"_type":"tag","name":"expand_levels","path":"a.py","line":17,"kind":"function",'
        '"signature":"(level:  Literal[\\"A\\",\\"B\\"])\\n  -> list"}'
    )

    symbols = parse_ctags_output(raw)

    assert symbols[0].signature == '(level: Literal["A","B"])'


def test_signature_is_truncated_to_limit() -> None:
    """超长签名必须截断，避免候选集把 state 撑爆（MUST-09 压缩精神）。"""
    raw = (
        '{"_type":"tag","name":"f","path":"a.py","line":1,"kind":"function",'
        f'"signature":"{"x" * 300}"}}'
    )

    symbols = parse_ctags_output(raw)

    assert len(symbols[0].signature) == SIGNATURE_LIMIT


def test_missing_signature_yields_empty_string() -> None:
    """老版 ctags / 非函数符号没有签名 → 空字符串，不影响其余字段。"""
    raw = '{"_type":"tag","name":"ok","path":"ok.py","line":9,"kind":"function"}'

    symbols = parse_ctags_output(raw)

    assert symbols[0].signature == ""
    assert symbols[0].name == "ok"


def test_cache_key_changes_with_mtime() -> None:
    k1 = cache_key("C:/proj", [("a.py", 111)])
    k2 = cache_key("C:/proj", [("a.py", 222)])
    k3 = cache_key("C:/other", [("a.py", 111)])
    assert k1 != k2  # mtime 变化 → 键变化（MUST-14）
    assert k1 != k3  # 路径变化 → 键变化（MUST-14）


def test_cache_key_order_insensitive() -> None:
    assert cache_key("p", [("a", 1), ("b", 2)]) == cache_key("p", [("b", 2), ("a", 1)])
