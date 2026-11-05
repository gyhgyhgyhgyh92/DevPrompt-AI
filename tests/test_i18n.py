"""后端文案层（2026-11-06，F-209 后端双语）。

``resolve_locale`` 决定用户看到哪种语言，``MESSAGES`` 的两语言键集必须严格一致——
任何一侧漏键在运行时表现为「界面中英混排」，只能靠测试拦住。
"""

from __future__ import annotations

import pytest

from devprompt_ai.common.i18n import DEFAULT_LOCALE, MESSAGES, resolve_locale, tr


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("en-US", "en"),
        ("EN-GB,en;q=0.9", "en"),
        ("en;q=0.8,zh-CN;q=0.9", "en"),
        ("zh-CN", "zh-CN"),
        ("zh", "zh-CN"),
        ("fr-FR", "zh-CN"),
        ("", "zh-CN"),
        (None, "zh-CN"),
        ("   ", "zh-CN"),
        ("*", "zh-CN"),
    ],
)
def test_resolve_locale(raw: str | None, expected: str) -> None:
    assert resolve_locale(raw) == expected


def test_two_locales_share_exact_key_set() -> None:
    zh, en = set(MESSAGES["zh-CN"]), set(MESSAGES["en"])
    assert zh == en
    assert len(zh) > 0


def test_no_empty_templates() -> None:
    for locale, table in MESSAGES.items():
        for key, template in table.items():
            assert template.strip() != "", f"{locale} 的 {key} 文案为空"


def test_tr_interpolates_and_falls_back() -> None:
    assert tr("progress.symbols", "zh-CN", total=42) == "符号表就绪，共 42 个符号参与匹配。"
    assert tr("progress.symbols", "en", total=42) == "Symbol table ready: 42 symbols are matched."
    # 缺键返回键名（暴露漏译，不抛异常）
    assert tr("progress.does_not_exist") == "progress.does_not_exist"
    # 插值参数缺失时返回模板原文，不抛异常
    assert tr("progress.symbols") == "符号表就绪，共 {total} 个符号参与匹配。"


def test_default_locale_is_zh() -> None:
    assert DEFAULT_LOCALE == "zh-CN"
    assert tr("progress.answering") == "正在回答你的追问。"
