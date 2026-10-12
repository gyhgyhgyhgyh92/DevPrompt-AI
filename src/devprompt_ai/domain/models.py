"""领域核心数据模型（阶段三~五共用；纯数据，无 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

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


@dataclass(slots=True)
class FlowSession:
    """F-002 流程会话（state 存 FlowState.value 字符串以便序列化）。"""

    session_id: str
    user_id: str
    state: str
    version: int = 0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionSummary:
    """F-501 会话摘要（GET /history 渲染用）：脱敏——不含原句明文（MUST-19）。

    title：自定义标题优先，否则原句截断（≤40）；pinned：置顶标记。
    project_root：项目全路径（供「复制项目路径」）；project 为其 basename，仅列表分组展示。
    """

    session_id: str
    state: str
    project: str
    updated_at: str
    title: str = ""
    pinned: bool = False
    project_root: str = ""


class SessionStore(Protocol):
    """L1 会话存储能力（MUST-11 乐观锁）。实现：memory/session_store.py。"""

    async def create(self, session: FlowSession) -> None: ...
    async def load(self, session_id: str) -> FlowSession | None: ...
    async def save(self, session: FlowSession) -> bool:
        """CAS 写入：WHERE version=旧值；0 行更新返回 False。"""
        ...

    async def list_recent(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        """最近会话摘要（pinned 优先 + updated_at 倒序）；项目名 = project_root basename。"""
        ...

    async def delete(self, session_id: str) -> bool:
        """物理删除会话；rowcount>0 为 True（不存在返回 False）。"""
        ...
