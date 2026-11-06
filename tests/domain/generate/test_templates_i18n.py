"""模板双语的结构等价（2026-11-06，F-209 后端双语）。

英文模板是「结构等价的翻译稿」，无法离线验证模型产出质量（零额度）；这里钉住
可以从代码层面断言的部分：三档 + 纯回答模板都有英文文案、边界声明两种语言都在、
证据字段名随语言切换而 JSON 指令部分保持逐字一致。
"""

from __future__ import annotations

from devprompt_ai.common.i18n import tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL
from devprompt_ai.domain.generate.templates import reply as reply_tpl

_CTX = GenerationContext(
    sentence="把提交按钮改成 primary-500",
    project_root=".",
    level="B",
    facts_summary="SubmitButton@src/ui/button.tsx:12",
    clarifications={"token_defined": "用 --color-primary-500"},
)


def test_each_level_has_english_role_and_chinese_role() -> None:
    keywords = {
        "A": ("保守版", "conservative"),
        "B": ("标准版", "standard"),
        "C": ("激进版", "aggressive"),
    }
    for level, (zh_word, en_word) in keywords.items():
        zh = TEMPLATE_BY_LEVEL[level].system("zh-CN")
        en = TEMPLATE_BY_LEVEL[level].system("en")
        assert zh_word in zh, f"{level} 档中文 role 缺失"
        assert en_word in en, f"{level} 档英文 role 缺失"
        # body 语义段也必须切换：这是决定方案正文语言的关键约束
        assert "【body 的语义" in zh
        assert "Semantics of `body`" in en


def test_boundary_declaration_present_in_both_languages() -> None:
    for tpl in TEMPLATE_BY_LEVEL.values():
        assert tr("template.boundary", "zh-CN") in tpl.system("zh-CN")
        assert tr("template.boundary", "en") in tpl.system("en")
        assert tr("template.boundary", "zh-CN") not in tpl.system("en")


def test_evidence_field_names_switch_but_json_instruction_stays() -> None:
    zh = TEMPLATE_BY_LEVEL["B"].build_user(_CTX, "zh-CN")
    en = TEMPLATE_BY_LEVEL["B"].build_user(_CTX, "en")
    assert "用户需求" in zh
    assert "user_request" in en
    assert "用户需求" not in en
    # JSON 指令部分是契约（模型按此解析），两种语言必须逐字一致
    for payload in ('{"title":', '"body":', '"changes":', '"level": "B"'):
        assert payload in zh
        assert payload in en


def test_reply_template_is_bilingual() -> None:
    assert "回答用户对已产出方案的追问" in reply_tpl.system_text("zh-CN")
    assert "answering a follow-up question" in reply_tpl.system_text("en")
    assert '"text"' in reply_tpl.build_user(_CTX, "en")
