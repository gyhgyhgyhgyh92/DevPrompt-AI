"""四层提示与增量协议（B1–B4）。

A 静态基座 / B 模型族校准 / C 动态上下文（会话内冻结）/ D 增量附录。
关键约定：**一轮之内只追加，不修改历史**；动态块用 `<context-update>` 增量下发，
「缺席 = 沿用上次」，无变化时发自闭合标签。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

_CONTEXT_HEADER: Final[str] = "context-update"


@dataclass(frozen=True, slots=True)
class PromptLayers:
    """一次会话的提示分层；C 层在会话内冻结。"""

    static: str
    model_family: str = ""
    context: Mapping[str, str] = field(default_factory=dict)
    seq: int = 0

    def frozen(self) -> tuple[str, str, dict[str, str]]:
        """返回可缓存的前缀（A+B+C），字节必须稳定。"""
        return self.static, self.model_family, dict(self.context)


def _render_block(name: str, text: str) -> str:
    return f"<{name}>\n{text}\n</{name}>"


def render_context_full(context: Mapping[str, str], *, seq: int) -> str:
    blocks = "\n".join(_render_block(name, text) for name, text in context.items())
    return f'<{_CONTEXT_HEADER} seq="{seq}" mode="full">\n{blocks}\n</{_CONTEXT_HEADER}>'


def render_delta(
    previous: Mapping[str, str] | None,
    current: Mapping[str, str],
    *,
    seq: int,
) -> str:
    """只发改动块；无变化时自闭合标签（明确告诉模型「沿用上次」）。"""
    if previous is None:
        return render_context_full(current, seq=seq)
    changed = {name: text for name, text in current.items() if previous.get(name) != text}
    removed = [name for name in previous if name not in current]
    if not changed and not removed:
        return f'<{_CONTEXT_HEADER} seq="{seq}"/>'
    body = [_render_block(name, text) for name, text in changed.items()]
    body.extend(f'<{name} removed="true"/>' for name in removed)
    return (
        f'<{_CONTEXT_HEADER} seq="{seq}" mode="delta">\n'
        + "\n".join(body)
        + f"\n</{_CONTEXT_HEADER}>"
    )


def assert_append_only(previous: Sequence[object], current: Sequence[object]) -> bool:
    """历史必须只追加：current 的前 len(previous) 项与 previous 逐项相同。"""
    if len(current) < len(previous):
        return False
    return all(
        left is right or left == right for left, right in zip(previous, current, strict=False)
    )
