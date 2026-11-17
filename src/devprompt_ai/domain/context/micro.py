"""micro compaction：不摘要，只截断，但**必须留可见标记**。

标记的作用是让模型知道「这里被截过」，避免把残缺输出当成完整事实下负向结论。
"""

from __future__ import annotations

from typing import Final

DEFAULT_PREVIEW_CHARS: Final[int] = 1_200


def micro_compact(text: str, *, preview_chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """超长文本截到 ``preview_chars``，并附原始长度与截断说明。"""
    limit = max(1, preview_chars)
    if len(text) <= limit:
        return text
    return (
        f"<microcompacted original_chars={len(text)}>\n"
        f"{text[:limit]}\n…（已截断，仅保留前 {limit} 字符）"
    )


def is_microcompacted(text: str) -> bool:
    """判断一段文本是否已被 micro compaction 处理过（幂等保护）。"""
    return text.startswith("<microcompacted ")
