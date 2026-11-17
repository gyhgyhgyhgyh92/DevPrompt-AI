"""自检与死路检测（E9–E10）：纯函数，只回答「该不该提醒」，不执行动作。

- self-verify：最近只做表层读取、没有任何 ground truth 验证 → 提醒一次；
- dead-end：同一动作连续失败 3 次 → 提示换路，而不是继续重试。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

#: 视为「验证」的动作：有 ground truth 输出。
VERIFY_ACTIONS: Final[frozenset[str]] = frozenset({"deliver", "generate"})
#: 视为「只读」的动作。
READ_ACTIONS: Final[frozenset[str]] = frozenset({"retrieve", "probe"})

_SELF_VERIFY_WINDOW: Final[int] = 5
#: 最小连击数：1~2 步只读是正常节奏（retrieve→probe→generate），
#: 达不到「一直在表层读取」的模式，不提醒。
_SELF_VERIFY_MIN: Final[int] = 3
_DEAD_END_REPEATS: Final[int] = 3


def needs_self_verify(recent_actions: Sequence[str]) -> bool:
    """最近窗口内只读且没有任何验证动作 → 建议先独立验证。"""
    window = list(recent_actions[-_SELF_VERIFY_WINDOW:])
    if len(window) < _SELF_VERIFY_MIN:
        return False
    if any(action in VERIFY_ACTIONS for action in window):
        return False
    return all(action in READ_ACTIONS for action in window)


def is_dead_end(recent: Sequence[tuple[str, str]]) -> bool:
    """``(action, outcome)`` 连续相同且失败 → 死路。"""
    tail = list(recent[-_DEAD_END_REPEATS:])
    if len(tail) < _DEAD_END_REPEATS:
        return False
    if len({item for item in tail}) != 1:
        return False
    return tail[0][1] == "failed"


def self_verify_hint() -> str:
    return "最近只做了读取类动作，先独立验证一次再下结论。"


def dead_end_hint(action: str) -> str:
    return f"动作 {action} 连续失败且没有新信息，换一种做法或直接问用户。"
