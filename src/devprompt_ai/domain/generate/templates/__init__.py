"""档位 → 模板路由（阶段五按 F-302/303/304 精化）+ 共用边界声明。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

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
from devprompt_ai.domain.prompt_guard import TASK_NOT_EXECUTE as _TASK_NOT_EXECUTE

#: T-2 由 `domain.prompt_guard` 定义（跨域共用，决策层也要用）。
#: 本模块只做**装配**：把边界声明附加到各档 SYSTEM 之后，避免三处重复文本。
TASK_NOT_EXECUTE: Final[str] = _TASK_NOT_EXECUTE


@dataclass(frozen=True, slots=True)
class VariantTemplate:
    """单档模板：SYSTEM 文案 + 用户消息构造器。"""

    system: str
    build_user: Callable[[GenerationContext], str]


#: 三档模板 + T-2 边界声明（M-7）。声明**附加在 SYSTEM 之后**，不改动各档原有约束。
TEMPLATE_BY_LEVEL: dict[str, VariantTemplate] = {
    "A": VariantTemplate(f"{A_SYSTEM}\n\n{TASK_NOT_EXECUTE}", a_build_user),
    "B": VariantTemplate(f"{B_SYSTEM}\n\n{TASK_NOT_EXECUTE}", b_build_user),
    "C": VariantTemplate(f"{C_SYSTEM}\n\n{TASK_NOT_EXECUTE}", c_build_user),
}
