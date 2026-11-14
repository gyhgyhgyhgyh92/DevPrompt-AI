"""通用域结构化校验（2026-11-14 领域包）：无仓库证据时的可机检交付标准。

work/life/creative 没有检索/取证/锚点——交付门改核「方案自身的结构完整性」：
四段小标题齐备、changes 交付物清单非空、无占位符残留。规则与通用域模板
（``domain.*.sections`` 文案）一一对应。

纯函数、零 I/O（MUST-06）：结构化判定只在这里，交付门（MUST-08）消费其结果。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: 通用域四段式小标题前缀：zh 模板要求「## 一、」～「## 四、」；en 模板指令段
#: 明确写了 heading 格式，模型按 zh 形态产出即可被校验覆盖。
_SECTION_MARKS: tuple[str, ...] = ("## 一、", "## 二、", "## 三、", "## 四、")

#: 占位符黑名单：「（推断）」是模板要求的合法标注，不在其列。
_PLACEHOLDERS: tuple[str, ...] = ("TODO", "TBD", "XXX", "待补充", "待填写")


@dataclass(frozen=True, slots=True)
class StructuralCheck:
    """一次结构化校验的结果。全部布尔/计数，无叙事文本。"""

    #: body 含全部四段小标题
    body_sections_ok: bool
    #: changes 交付物清单非空（模板已强制「逐条列出交付物」）
    deliverables_declared: bool
    #: 正文残留占位符数量（TODO/待补充 等）
    placeholder_count: int


def check_structural(body: str, changes: Sequence[str]) -> StructuralCheck:
    """对通用域方案正文与交付物清单做结构校验。"""
    sections_ok = all(mark in body for mark in _SECTION_MARKS)
    placeholder_count = sum(body.count(marker) for marker in _PLACEHOLDERS)
    return StructuralCheck(
        body_sections_ok=sections_ok,
        deliverables_declared=bool(changes and any(item.strip() for item in changes)),
        placeholder_count=placeholder_count,
    )
