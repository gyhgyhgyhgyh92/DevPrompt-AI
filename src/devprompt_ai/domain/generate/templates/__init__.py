"""档位 → 模板路由（阶段五按 F-302/303/304 精化）+ 共用边界声明。

2026-11-06 双语：``system`` 改为「按语言取文案」的可调用对象，边界声明（T-2）
也从语言包取，与各档 SYSTEM 一起切换语言。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.generate.templates import reply as reply_tpl
from devprompt_ai.domain.generate.templates.a_conservative import (
    build_user as a_build_user,
)
from devprompt_ai.domain.generate.templates.a_conservative import (
    system_text as a_system_text,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    build_user as b_build_user,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    system_text as b_system_text,
)
from devprompt_ai.domain.generate.templates.c_thorough import (
    build_user as c_build_user,
)
from devprompt_ai.domain.generate.templates.c_thorough import (
    system_text as c_system_text,
)
from devprompt_ai.domain.prompt_guard import TASK_NOT_EXECUTE as _TASK_NOT_EXECUTE

#: T-2 边界声明（中文常量，保留给决策层等旧引用）。
TASK_NOT_EXECUTE: Final[str] = _TASK_NOT_EXECUTE


@dataclass(frozen=True, slots=True)
class VariantTemplate:
    """单档模板：SYSTEM 文案（按语言取） + 用户消息构造器。"""

    system: Callable[[Locale], str]
    build_user: Callable[[GenerationContext, Locale], str]


def _with_boundary(system_text: Callable[[Locale], str], locale: Locale) -> str:
    """各档 SYSTEM 之后附加 T-2 边界声明（M-7），不重复文本。"""
    return f"{system_text(locale)}\n\n{tr('template.boundary', locale)}"


#: 三档模板 + T-2 边界声明（M-7）。
TEMPLATE_BY_LEVEL: dict[str, VariantTemplate] = {
    "A": VariantTemplate(lambda locale: _with_boundary(a_system_text, locale), a_build_user),
    "B": VariantTemplate(lambda locale: _with_boundary(b_system_text, locale), b_build_user),
    "C": VariantTemplate(lambda locale: _with_boundary(c_system_text, locale), c_build_user),
}

#: 纯回答轮的模板（同一套接口，便于调用方按语义切换）。
REPLY_TEMPLATE: Final[VariantTemplate] = VariantTemplate(
    reply_tpl.system_text, reply_tpl.build_user
)

#: 默认语言下的 SYSTEM（旧引用兜底）。
DEFAULT_SYSTEM: Final[str] = TEMPLATE_BY_LEVEL["A"].system(DEFAULT_LOCALE)
