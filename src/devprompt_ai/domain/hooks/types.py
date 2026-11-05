"""运行时 hook 契约（2026-11-04；纯声明，零 I/O，MUST-06）。

只保留「契约」这一层：阶段枚举、上下文、返回值。不引入插件发现、热加载或多阶段装配。

2026-11-05 外环监督扩展：阶段从 3 个扩到 5 个（新增 ``pre_turn`` / ``post_tool``），
返回值新增 ``verdict`` 三态。旧三值**不重命名**，既有 hook 与测试零改动。

与 Tianshu 的差别：它用 Proxy 冻结 effects 阻止超时 hook 改状态；这里 hook **只返回值**，
超时的返回值天然被丢弃，不需要额外机制。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

#: 五个横切点：轮前装配 / 取证后 / 单步执行后 / 生成后 / 一轮结束后。
#: 排序即执行顺序，``post_tool`` 是外环监督唯一能影响下一步决策的位置。
HookPhase = Literal[
    "pre_turn",
    "after_retrieval",
    "post_tool",
    "after_generate",
    "after_turn",
]

#: hook 对外环的建议。``allow`` 不产生副作用；``correct`` 注入纠偏提示后继续；
#: ``halt`` 要求本轮立即终止（由 service 决定如何收尾，领域层不碰状态机）。
HookVerdict = Literal["allow", "correct", "halt"]


@dataclass(frozen=True, slots=True)
class HookContext:
    """一次 hook 调用的输入快照（只读）。"""

    phase: HookPhase
    session_state: str
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HookResult:
    """hook 的产出：要合并回会话的字段 + 是否跳过 + 对外环的建议。

    ``skipped=True`` 表示本次不适用（例如没有 notes 可写），不产生事件、不合并数据。
    ``verdict`` 默认 ``allow``：现有 hook 不必改造即可继续工作。
    """

    data: Mapping[str, Any] = field(default_factory=dict)
    skipped: bool = False
    verdict: HookVerdict = "allow"
    reason: str = ""


@runtime_checkable
class Hook(Protocol):
    """同步 hook：实现方不得做长阻塞 I/O（超时由管线兜底）。"""

    name: str
    phase: HookPhase

    def run(self, ctx: HookContext) -> HookResult: ...
