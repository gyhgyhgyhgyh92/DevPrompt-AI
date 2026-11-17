"""生成模板路由（2026-11-11 单套输出）：B 常规 / A 兜底 / reply。

只保留三个入口：常规轮次恒用 ``b_standard``；``a_conservative`` 仅在主流程抛错或
产出无效时兜底，**禁止**进入常规路径；``reply`` 供讨论性追问。

2026-11-06 双语：``system`` 改为「按语言取文案」的可调用对象，边界声明（T-2）
也从语言包取，与各档 SYSTEM 一起切换语言。
2026-11-14 领域包：``system`` 增第二参数 domain_id（默认 "code"），分段语义随域切换。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from devprompt_ai.common.i18n import Locale, tr
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


@dataclass(frozen=True, slots=True)
class VariantTemplate:
    """单套模板：SYSTEM 文案（按语言与领域取） + 用户消息构造器。"""

    system: Callable[[Locale, str], str]
    build_user: Callable[[GenerationContext, Locale], str]


def _with_boundary(
    system_text: Callable[[Locale, str], str], locale: Locale, domain_id: str
) -> str:
    """模板 SYSTEM 之后附加 T-2 边界声明（M-7），不重复文本。"""
    return f"{system_text(locale, domain_id)}\n\n{tr('template.boundary', locale)}"


#: 常规路径唯一出口：B 标准版。
STANDARD_TEMPLATE: Final[VariantTemplate] = VariantTemplate(
    lambda locale, domain_id: _with_boundary(b_system_text, locale, domain_id), b_build_user
)

#: 异常兜底专用：A 保守版。正常轮次不得使用。
CONSERVATIVE_TEMPLATE: Final[VariantTemplate] = VariantTemplate(
    lambda locale, domain_id: _with_boundary(a_system_text, locale, domain_id), a_build_user
)

#: 纯回答轮的模板（同一套接口，便于调用方按语义切换）。
REPLY_TEMPLATE: Final[VariantTemplate] = VariantTemplate(
    lambda locale, _domain_id: reply_tpl.system_text(locale), reply_tpl.build_user
)


def template_for(fallback: bool = False) -> VariantTemplate:
    """按是否兜底选模板：常规恒为 B，仅异常兜底才用 A。"""
    return CONSERVATIVE_TEMPLATE if fallback else STANDARD_TEMPLATE
