"""Web 契约模型（Pydantic v2，XxxRequest/XxxResponse 命名）。

错误响应仅含 code + message + request_id，不回传堆栈（MUST-19）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class OptimizeRequest(BaseModel):
    """POST /optimize 请求体（该端点有副作用，客户端禁重试，MUST-15）。"""

    sentence: str
    project: str


class FollowupRequest(BaseModel):
    """POST /followup/{flow_id} 三模式请求体：answers / escape / guardrail_action 互斥。"""

    answers: dict[str, str] | None = None
    escape: bool = False
    guardrail_action: Literal["continue", "generate"] | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> FollowupRequest:
        modes = [self.answers is not None, self.escape, self.guardrail_action is not None]
        if sum(modes) != 1:
            raise ValueError("answers / escape / guardrail_action 三模式互斥，且必须提供其一")
        return self


class FeedbackRequest(BaseModel):
    """POST /feedback 请求体：variant 采纳 / +edited_text 编辑采纳 / 两者皆无=跳过。"""

    session_id: str
    action: str
    variant: Literal["A", "B", "C"] | None = None
    edited_text: str | None = None


class UnknownItemPayload(BaseModel):
    """domain UnknownItem 的契约镜像（仅渲染字段）。"""

    key: str
    reason: str
    best_guess: str
    ask: str


class VariantPayload(BaseModel):
    """domain VariantDraft 的契约镜像（F-301 结构化方案）。"""

    title: str
    body: str
    changes: list[str] = Field(default_factory=list)
    level: str


class RankingViewPayload(BaseModel):
    """service.RankingView 的契约镜像（F-403/F-404 加权推荐视图）。"""

    variant: str
    gap: float
    confidence: float
    marked: bool
    reason: str
    fit: float
    pref: float
    total: float


class FlowSnapshotResponse(BaseModel):
    """FlowSnapshot 的 HTTP 渲染形态（status 含 SSE 专有扩展值 "aborted"）。

    v2（BREAKING）：variant 单数字段 → variants 列表 + ranking 推荐视图。
    """

    session_id: str
    status: str
    state: str
    questions: list[UnknownItemPayload] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    variants: list[VariantPayload] = Field(default_factory=list)
    ranking: RankingViewPayload | None = None
    message: str = ""


class HealthCheckItem(BaseModel):
    """单项自检结果。"""

    name: str
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    """GET /health 数据体：checks 列表 + 总体健康位。"""

    checks: list[HealthCheckItem]
    is_healthy: bool


class ScanResponse(BaseModel):
    """GET /project/scan 数据体：符号表统计（F-101 只读透出）。"""

    total_symbols: int
    total_files: int
    kind_counts: dict[str, int]


class ApiResponse(BaseModel):
    """统一响应信封：code=0 成功；非 0 为架构文档 §3.3 错误码。"""

    code: int = 0
    message: str = "ok"
    data: Any = None
    request_id: str = ""
