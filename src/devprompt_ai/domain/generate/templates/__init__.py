"""档位 → 模板路由（阶段五按 F-302/303/304 精化）。"""

from collections.abc import Callable
from dataclasses import dataclass

from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.generate.templates.a_conservative import (
    SYSTEM as A_SYSTEM,
)
from devprompt_ai.domain.generate.templates.a_conservative import (
    build_user as a_build_user,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    SYSTEM as B_SYSTEM,
)
from devprompt_ai.domain.generate.templates.b_standard import (
    build_user as b_build_user,
)
from devprompt_ai.domain.generate.templates.c_thorough import (
    SYSTEM as C_SYSTEM,
)
from devprompt_ai.domain.generate.templates.c_thorough import (
    build_user as c_build_user,
)


@dataclass(frozen=True, slots=True)
class VariantTemplate:
    """单档模板：SYSTEM 文案 + 用户消息构造器。"""

    system: str
    build_user: Callable[[GenerationContext], str]


TEMPLATE_BY_LEVEL: dict[str, VariantTemplate] = {
    "A": VariantTemplate(A_SYSTEM, a_build_user),
    "B": VariantTemplate(B_SYSTEM, b_build_user),
    "C": VariantTemplate(C_SYSTEM, c_build_user),
}
