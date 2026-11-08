"""BM25 + RRF（I1–I2）：零依赖的二次排序层，用于给 ripgrep 命中重排。

中文按 bigram 切：没有分词器也能得到稳定的字面匹配；英文按单词切。
RRF 只融合名次、不融合分数，避免两套打分口径不可比。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

#: 下划线也作为分隔符：`export_button` 应能被「export button」命中。
_ASCII_WORD: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CJK: Final = re.compile(r"[\u4e00-\u9fff]+")
_K1: Final = 1.5
_B: Final = 0.75


def tokenize(text: str) -> list[str]:
    tokens = [word.lower() for word in _ASCII_WORD.findall(text)]
    for block in _CJK.findall(text):
        if len(block) == 1:
            tokens.append(block)
            continue
        tokens.extend(block[i : i + 2] for i in range(len(block) - 1))
    return tokens


class BM25Index:
    def __init__(self, documents: Mapping[str, str]) -> None:
        self._docs = {key: tokenize(text) for key, text in documents.items()}
        self._lengths = {key: len(tokens) for key, tokens in self._docs.items()}
        self._avg_len = sum(self._lengths.values()) / len(self._lengths) if self._lengths else 0.0
        self._freqs = {key: Counter(tokens) for key, tokens in self._docs.items()}
        self._df: Counter[str] = Counter()
        for counts in self._freqs.values():
            self._df.update(counts.keys())

    def search(self, query: str, *, limit: int = 25) -> list[tuple[str, float]]:
        terms = tokenize(query)
        if not terms or not self._docs:
            return []
        total = len(self._docs)
        scored: list[tuple[str, float]] = []
        for key, counts in self._freqs.items():
            score = 0.0
            length = self._lengths[key] or 1
            for term in terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (total - self._df[term] + 0.5) / (self._df[term] + 0.5))
                denom = freq + _K1 * (1 - _B + _B * length / (self._avg_len or 1))
                score += idf * freq * (_K1 + 1) / denom
            if score > 0:
                scored.append((key, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


def rrf(rankings: Sequence[Sequence[str]], *, k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion：名次越靠前分越高，与原始分数尺度无关。"""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
    return dict(sorted(fused.items(), key=lambda pair: pair[1], reverse=True))
