"""领域核心数据模型（阶段三~五共用；纯数据，无 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SymbolKind = Literal["function", "class", "variable", "other"]
CandidateSource = Literal["symbol", "path"]
FactKey = Literal[
    "target_file_exists",
    "symbol_in_file",
    "token_defined",
    "has_data_testid",
    "has_state_styles",
    "file_type_matches",
    "test_file_exists",
]


@dataclass(frozen=True, slots=True)
class Symbol:
    """F-101 输出：符号名 + 相对路径(POSIX) + 行号 + 类型。"""

    name: str
    path: str
    line: int
    kind: SymbolKind


@dataclass(frozen=True, slots=True)
class Candidate:
    """F-102 输出元素：仅符号名与路径，不含代码正文（MUST-09）。"""

    name: str
    path: str
    line: int
    score: float
    source: CandidateSource


@dataclass(frozen=True, slots=True)
class CodeLocation:
    """F-103 输出：定位与取证上下文。"""

    symbol_name: str
    path: str
    definition_line: int
    selectors: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FactResult:
    """F-104 输出元素：七项事实之一，布尔 + 证据，无「未知」。"""

    key: FactKey
    passed: bool
    evidence: str
