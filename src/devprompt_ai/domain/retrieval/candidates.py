"""F-102 候选检索：原句词元 × 符号词元 打分排序，硬约束 ≤25 条（MUST-09）。

纯函数零 I/O；候选仅符号名+路径，类型层无正文字段。
来源通道：symbol（符号名命中）/ path（路径词元命中）。
「similarity」通道为 F-801 不达标时的重做预案（放宽匹配/模糊匹配），首版不实现——
按真源 §4.4 门禁处置：召回率 <80% 时才加强，避免过早优化。
"""

from __future__ import annotations

from dataclasses import dataclass

from devprompt_ai.common.text import split_identifier, tokenize_sentence
from devprompt_ai.domain.models import Candidate, CandidateSource, Symbol

MAX_CANDIDATES = 25  # MUST-09 硬约束：超出按匹配度截断，不报错
MIN_CANDIDATES = 3  # F-102：少于 3 条触发人工指定流程

_SYMBOL_WEIGHT = 2.0
_PATH_WEIGHT = 1.0


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidates: list[Candidate]
    total_matched: int
    manual_required: bool


def _score_symbol(sentence_terms: set[str], symbol: Symbol) -> tuple[float, CandidateSource] | None:
    """词元重叠打分：符号名命中权重 2、路径词元命中权重 1；零命中返回 None。"""
    name_terms = set(split_identifier(symbol.name))
    name_hits = len(name_terms & sentence_terms)

    path_terms = set(split_identifier(symbol.path))
    path_hits = len(path_terms & sentence_terms)

    score = name_hits * _SYMBOL_WEIGHT + path_hits * _PATH_WEIGHT
    if score <= 0:
        return None
    source: CandidateSource = "symbol" if name_hits > 0 else "path"
    return score, source


def build_candidates(sentence: str, symbols: list[Symbol]) -> CandidateResult:
    """从符号表构建候选集：打分 → 降序 → 截断 25 → <3 置人工标志。"""
    sentence_terms = set(tokenize_sentence(sentence))

    scored: list[Candidate] = []
    for sym in symbols:
        hit = _score_symbol(sentence_terms, sym)
        if hit is None:
            continue
        score, source = hit
        scored.append(
            Candidate(name=sym.name, path=sym.path, line=sym.line, score=score, source=source)
        )

    scored.sort(key=lambda c: (-c.score, len(c.name), c.path))

    total_matched = len(scored)
    truncated = scored[:MAX_CANDIDATES]  # 超限截断而非报错（MUST-09）
    manual_required = len(truncated) < MIN_CANDIDATES
    return CandidateResult(
        candidates=truncated, total_matched=total_matched, manual_required=manual_required
    )
