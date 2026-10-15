"""文本分词纯工具：中文按字符二元组、英文按驼峰/分隔符拆分（F-102 的匹配基元）。

无业务语义、无 I/O（§4.7）。
"""

from __future__ import annotations

import re

# 连续 CJK 段（含汉字扩展区）
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
# 单个 CJK 字符（与 _CJK_RUN 同区段），用于 token 粗估
_CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 连续 ASCII 词段（字母数字）
_ASCII_RUN = re.compile(r"[A-Za-z0-9]+")
# 驼峰边界：小写/数字→大写，或 大写串→大写+小写（HTTPServer → HTTP|Server）
_CAMEL_SPLIT = re.compile(r"[A-Z]+(?=[A-Z][a-z0-9])|[A-Z]?[a-z0-9]+|[A-Z]+")


def split_identifier(name: str) -> list[str]:
    """将标识符/路径拆为小写词元：驼峰、下划线、连字符、点、斜杠均为边界。

    例：SubmitButton -> [submit, button]；src/v2/UserList.tsx -> [src, v2, user, list, tsx]
    """
    words: list[str] = []
    for raw in _ASCII_RUN.findall(name):
        words.extend(w.lower() for w in _CAMEL_SPLIT.findall(raw) if w)
    return words


def cjk_bigrams(text: str) -> list[str]:
    """将文本中的连续中文段切为相邻二元组；单字段保留单字。"""
    grams: list[str] = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def tokenize_sentence(sentence: str) -> list[str]:
    """从原句提取匹配词元：英文词元 + 中文二元组，去重保序。

    例："把用户中心页面的提交按钮背景色改为 primary-500"
      -> [用户, 中心, 页面, 面的, 提交, 交按, 按钮, 背, 背景, 景色, 色改, 改为, primary, 500]
    """
    terms: list[str] = []
    for word in split_identifier(sentence):
        if word not in terms:
            terms.append(word)
    for gram in cjk_bigrams(sentence):
        if gram not in terms:
            terms.append(gram)
    return terms


def estimate_tokens(text: str) -> int:
    """粗估文本 token 数（MUST-09 state 提交前预校验；无外部依赖的启发式）。

    约定：CJK 字符 ≈1 token；其余字符每 4 个 ≈1 token（向上取整）。
    仅供超限判断与截断定位，非精确计数——按 MUST-04 不引入 tokenizer 依赖。
    """
    cjk = len(_CJK_CHAR.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4
