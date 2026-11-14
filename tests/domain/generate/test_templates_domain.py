"""模板领域感知测试：code 域文案不变、通用域切换分段/指令/claims 规则。"""

from __future__ import annotations

from devprompt_ai.common.i18n import DEFAULT_LOCALE
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.generate.templates.a_conservative import (
    system_text as a_system_text,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    build_user as b_build_user,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    system_text as b_system_text,
)


def _ctx(domain_id: str = "code") -> GenerationContext:
    return GenerationContext(sentence="测试需求", project_root="/tmp/p", domain_id=domain_id)


def test_code_system_unchanged() -> None:
    system = b_system_text(DEFAULT_LOCALE, "code")
    assert "## 一、定位文件与组件" in system
    assert "原代码 → 新代码" in system
    # code 域复用既有 sections 键（零回归锚点）
    assert b_system_text(DEFAULT_LOCALE, "code") == b_system_text(DEFAULT_LOCALE)


def test_generic_system_switches_sections() -> None:
    system = b_system_text(DEFAULT_LOCALE, "work")
    assert "目标与背景" in system
    assert "## 一、定位文件与组件" not in system
    assert "证据中没有的一律标注（推断）" in system


def test_a_conservative_generic_sections() -> None:
    system = a_system_text(DEFAULT_LOCALE, "creative")
    assert "创意定位" in system
    assert "未能定位具体文件" not in system
    # code 域兜底仍用原四段式
    assert "未能定位具体文件" in a_system_text(DEFAULT_LOCALE, "code")


def test_generic_user_injects_domain_directives() -> None:
    user = b_build_user(_ctx("work"), DEFAULT_LOCALE)
    assert "领域指令" in user
    assert "未指明时间范围时按「本周」处理" in user
    assert "domain.work.directives" not in user  # 渲染的是文案不是键名


def test_generic_user_switches_claims_rules() -> None:
    user = b_build_user(_ctx("life"), DEFAULT_LOCALE)
    assert "无需声明代码断言" in user
    assert "逐条声明" not in user


def test_code_user_has_no_domain_field() -> None:
    user = b_build_user(_ctx("code"), DEFAULT_LOCALE)
    assert "领域指令" not in user  # code 域连占位字段都不注入（prompt 逐字不变）
    assert "逐条声明" in user
