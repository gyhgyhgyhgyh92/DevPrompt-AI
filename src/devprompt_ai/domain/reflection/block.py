"""经验区块的合并 / 裁剪 / 渲染（纯函数，零 I/O，MUST-06）。

分成三层便于逐层单测：

1. ``merge_hits``  —— 两桶合并：项目桶优先、文本去重、按相关度稳定排序；
2. ``fit_block``   —— 字符预算裁剪，返回是否发生截断（供事件如实披露）；
3. ``render_block``—— 渲染成带小标题的纯文本，直接拼进 system prompt。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.reflection.port import ReflectionHit, ReflectionScope

#: 单条经验最大字符数：侧车可能返回整段落，先压到「一句可复用结论」的量级。
MAX_HIT_CHARS: Final = 400


def _clean(text: str) -> str:
    """折叠空白并截断到单条上限；空文本返回空串（调用方据此跳过）。"""
    return " ".join(text.split())[:MAX_HIT_CHARS].strip()


def merge_hits(
    project: Sequence[ReflectionHit], global_: Sequence[ReflectionHit], top_k: int
) -> list[ReflectionHit]:
    """合并两桶候选：按 score 降序（同分时项目桶在前）、文本去重、截到 ``top_k``。

    ``top_k <= 0`` 视为不限条数（仍去重）。
    """
    ordered = sorted([*project, *global_], key=lambda hit: hit.score, reverse=True)
    merged: list[ReflectionHit] = []
    seen: set[str] = set()
    for hit in ordered:
        text = _clean(hit.text)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(ReflectionHit(scope=hit.scope, text=text, score=hit.score))
    return merged[:top_k] if top_k > 0 else merged


def fit_block(hits: Sequence[ReflectionHit], max_chars: int) -> tuple[list[ReflectionHit], bool]:
    """按字符预算逐条累加；返回（保留条目, 是否发生截断）。"""
    if max_chars <= 0:
        return ([], bool(hits))
    kept: list[ReflectionHit] = []
    used = 0
    for hit in hits:
        if used + len(hit.text) > max_chars:
            return (kept, True)
        kept.append(hit)
        used += len(hit.text)
    return (kept, False)


def render_block(hits: Sequence[ReflectionHit], locale: Locale = DEFAULT_LOCALE) -> str:
    """渲染成「标题 + 逐条桶标签」的纯文本；空输入返回空串（调用方据此不注入）。"""
    if not hits:
        return ""
    lines = [tr("reflection.block.title", locale)]
    for hit in hits:
        label = tr(
            "reflection.block.project"
            if hit.scope is ReflectionScope.PROJECT
            else "reflection.block.global",
            locale,
        )
        lines.append(f"- [{label}] {hit.text}")
    return "\n".join(lines)
