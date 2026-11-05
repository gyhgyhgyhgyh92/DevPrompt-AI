"""C 档锚点校验纯函数（2026-11-06 U-2）。

抽取与聚合直接决定「要不要把 C 档降为 B」，判错会误伤正常方案，故单独钉住。
"""

from __future__ import annotations

from devprompt_ai.domain.generate.anchors import (
    Anchor,
    extract_anchors,
    is_project_relative,
    verify_anchors,
)


def test_extract_backticked_and_bare_anchors() -> None:
    body = (
        "改 `src/click/utils.py:123` 的 echo；另见 src/app.py:8。\n"
        "重复引用 src/click/utils.py:123 不再计数。"
    )
    anchors = extract_anchors(body)
    assert anchors == (
        Anchor(path="src/click/utils.py", line=123),
        Anchor(path="src/app.py", line=8),
    )


def test_extract_skips_urls_and_absolute_paths() -> None:
    body = (
        "参考 https://example.com/a.py:1 与 C:\\repo\\b.py:2 与 ~/x.py:3，"
        "但 src/real.py:4 有效；无行号的 src/only.py 不算锚点，「注意:123」也不算。"
    )
    anchors = extract_anchors(body)
    assert anchors == (Anchor(path="src/real.py", line=4),)


def test_is_project_relative() -> None:
    assert is_project_relative("src/a.py") is True
    assert is_project_relative("src\\a.py") is True
    assert is_project_relative("C:\\repo\\a.py") is False
    assert is_project_relative("/abs/a.py") is False
    assert is_project_relative("https://x/a.py") is False
    assert is_project_relative("~/a.py") is False


def test_verify_counts_only_explicit_invalid() -> None:
    verdicts = [
        (Anchor(path="src/a.py", line=1), True),
        (Anchor(path="src/gone.py", line=3), False),
        (Anchor(path="src/unclear.py", line=9), None),
    ]
    report = verify_anchors(verdicts)
    assert report.total == 3
    assert report.invalid == ("src/gone.py:3",)


def test_verify_empty_is_clean() -> None:
    report = verify_anchors([])
    assert report.total == 0
    assert report.invalid == ()
