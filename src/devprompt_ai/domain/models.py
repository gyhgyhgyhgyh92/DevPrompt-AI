"""领域核心数据模型（阶段三~五共用；纯数据，无 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

T = TypeVar("T")

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
    """F-101 输出：符号名 + 相对路径(POSIX) + 行号 + 类型 + 签名。

    ``signature``（2026-11-05）：ctags 的 ``{signature}`` 字段，仅参数列表，≤1 行 ≤120 字符。
    默认空字符串保证旧数据反序列化与既有位置参数零变化。
    """

    name: str
    path: str
    line: int
    kind: SymbolKind
    signature: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    """F-102 输出元素：符号名、路径与签名，**不含代码正文**（MUST-09）。

    ``signature``（2026-11-05）：允许携带 ≤1 行签名，用于让排序决策层区分同名同路径候选；
    仍不含函数体（MUST-09 的硬边界不变）。
    """

    name: str
    path: str
    line: int
    score: float
    source: CandidateSource
    signature: str = ""


@dataclass(frozen=True, slots=True)
class CodeLocation:
    """F-103 输出：定位与取证上下文。"""

    symbol_name: str
    path: str
    definition_line: int
    selectors: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Page(Generic[T]):
    """分页结果（2026-11-05）：列表端点的统一返回形态。

    ``has_more`` 而非 ``total``：存储层按「取 limit+1 条」探测还有没有下一页，
    不必额外做一次 COUNT 查询，也不必把总数算准。裸数组无法表达「还有更多」，
    前端只能硬顶（20 轮 / 50 会话）。

    不加 ``slots=True``：``dataclass(slots=True)`` 与 ``Generic`` 在 Python 3.10
    （项目最低版本）组合会出问题，frozen 已足够。
    """

    items: tuple[T, ...]
    has_more: bool
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class FactResult:
    """F-104 输出元素：七项事实之一，布尔 + 证据，无「未知」。

    ``applicable``（2026-11-05）：该事实在当前目标文件类型下是否有意义。
    默认 ``True`` 保证旧数据反序列化、旧调用方位置参数与既有断言零变化；
    非前端项目把样式类三项标为不适用，档位判定从此只看适用项。
    """

    key: FactKey
    passed: bool
    evidence: str
    applicable: bool = True


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


@dataclass(slots=True)
class TurnRecord:
    """多轮中的一个 turn（append-only）：状态机作用域下沉到它，session 只是容器。

    ``output`` 为方案全文（懒加载），``summary`` 为机器摘要（装配上下文只读它）。
    """

    turn_id: str
    session_id: str
    turn_index: int
    state: str
    input: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    clarifications: dict[str, str] = field(default_factory=dict)
    output: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class ProjectNote:
    """L2 项目记忆条目（结构化，2026-10-20）：检索式注入的唯一真源。

    key 归一化为 `符号名小写@路径末两段`；重命名通过 `superseded_by` 覆盖而非删除。
    """

    project_root: str
    kind: str
    key: str
    value: str
    evidence: str = ""
    confidence: float = 0.5
    hit_count: int = 0
    last_hit_at: str = ""
    superseded_by: str = ""
    source: str = "auto"

    def render(self) -> str:
        """注入 prompt 的一行文本（不含绝对路径）。"""
        return f"[{self.kind}] {self.value}"


class ProjectNoteStore(Protocol):
    """L2 项目记忆读写能力（top-K 检索 + 命中回写）。"""

    async def upsert(self, note: ProjectNote) -> None: ...

    async def record_from_session(self, project_root: str, data: dict[str, Any]) -> None:
        """从本轮会话数据写入 target / decision / rejected_option（自动级）。"""
        ...

    async def search(
        self, project_root: str, *, target_key: str = "", limit: int = 5
    ) -> list[ProjectNote]:
        """按 confidence × 衰减 × key 匹配度排序取前 N，并回写命中计数。"""
        ...


class TurnStore(Protocol):
    """turn 存储能力（MUST-11：`(session_id, turn_index)` 唯一索引即乐观锁）。"""

    async def append(self, turn: TurnRecord) -> None:
        """追加一轮；同索引已存在时由实现抛冲突（映射 6001）。"""
        ...

    async def finish(
        self,
        turn_id: str,
        *,
        state: str,
        facts: list[dict[str, Any]],
        clarifications: dict[str, str],
        output: list[dict[str, Any]],
        summary: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """回填占位 turn 的产出（一轮只写一行，不回写历史）。"""
        ...

    async def list_for_session(
        self, session_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[TurnRecord]:
        """按 turn_index 升序返回该会话轮次（摘要 + 正文一起读，正文调用方可忽略）。

        分页语义：``limit=None`` 取全部（升序）；给定 ``limit`` 时**从最新一轮往回数**
        ``offset`` 条、取 ``limit`` 条，返回仍按 turn_index 升序——「加载更早」用。
        """
        ...

    async def load(self, turn_id: str) -> TurnRecord | None: ...

    async def delete_after(self, session_id: str, turn_index: int) -> int:
        """物理删除 turn_index 之后的所有轮次，返回删除行数（2026-11-05 撤销）。

        MUST-32 修订：撤销是**显式用户操作**，允许物理删除其后的轮次；
        策略判断（终态校验、归属校验、事件留痕）在 service 层，存储层只管执行。
        """
        ...


class SessionStore(Protocol):
    """L1 会话存储能力（MUST-11 乐观锁）。实现：memory/session_store.py。"""

    async def create(self, session: FlowSession) -> None: ...
    async def load(self, session_id: str) -> FlowSession | None: ...
    async def save(self, session: FlowSession) -> bool:
        """CAS 写入：WHERE version=旧值；0 行更新返回 False。"""
        ...

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        """最近会话摘要（pinned 优先 + updated_at 倒序）；项目名 = project_root basename。

        分页语义：排序后从第 ``offset`` 条起取 ``limit`` 条。
        """
        ...

    async def delete(self, session_id: str) -> bool:
        """物理删除会话；rowcount>0 为 True（不存在返回 False）。"""
        ...

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        """项目级批量删除：按 payload.project_root 匹配后一次删净，返回删除条数。"""
        ...
