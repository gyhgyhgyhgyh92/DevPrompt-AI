"""token 估算（分字符口径，无第三方依赖）。

为什么不用 tiktoken：本工具接多供应商，没有统一 tokenizer；为一个粗粒度预算判断
引入依赖违反 MUST-04。误差方向刻意偏高估（安全侧），用于压缩/预算判断足够。

口径移植自天枢 `src/compact/micro.ts:180-198`：ASCII 4 字符/token，CJK 1.2 字符/token。
"""

from __future__ import annotations

import math
from typing import Final

#: CJK 区段：统一表意（含扩展 A/B）+ 平假名 + 片假名 + 韩文音节。
_CJK_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x20000, 0x2A6DF),
    (0x3040, 0x309F),
    (0x30A0, 0x30FF),
    (0xAC00, 0xD7AF),
)

_CHARS_PER_ASCII_TOKEN: Final[float] = 4.0
_CHARS_PER_CJK_TOKEN: Final[float] = 1.2


def _is_cjk(code: int) -> bool:
    return any(low <= code <= high for low, high in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """估算文本 token 数：ASCII 与 CJK 分别取整后相加。"""
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(ord(char)))
    ascii_chars = len(text) - cjk
    return math.ceil(ascii_chars / _CHARS_PER_ASCII_TOKEN) + math.ceil(cjk / _CHARS_PER_CJK_TOKEN)


def estimate_message_tokens(
    content: str,
    *,
    tool_calls_json: str = "",
    reasoning: str = "",
) -> int:
    """估算一条 assistant 消息的 token。

    tool_calls 的 JSON 语法与 reasoning 正文都必须计入：漏算 reasoning 会让工具密集
    会话的压缩系统性偏晚（天枢实测结论）。
    """
    return estimate_tokens(content) + estimate_tokens(tool_calls_json) + estimate_tokens(reasoning)
