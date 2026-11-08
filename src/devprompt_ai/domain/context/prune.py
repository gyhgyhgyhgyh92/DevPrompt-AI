"""语义剪枝：**只替换 content，绝不 splice 数组**。

splice 会让后续所有消息索引位移，缓存前缀全部失效、按 cacheWrite 溢价重发；
因此这里只返回一段更短的占位正文，由调用方就地替换。
"""

from __future__ import annotations


def prune_content(text: str, *, reason: str, artifact_id: str = "") -> str:
    """把正文替换为「已剪枝 + 归档指针」的最小占位。"""
    ref = f"[artifact:{artifact_id}]" if artifact_id else "（未归档）"
    return f"[pruned: {reason}] 原内容 {len(text)} 字符 {ref}"


def is_pruned(text: str) -> bool:
    return text.startswith("[pruned:")
