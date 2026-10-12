"""Web 契约模型（Pydantic v2，XxxRequest/XxxResponse 命名）。

错误响应仅含 code + message + request_id，不回传堆栈（MUST-19）。
ApiResponse 泛型化：data 体类型进 OpenAPI，供前端类型生成精确对齐（F-705）。
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

DataT = TypeVar("DataT")


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


class SymbolPayload(BaseModel):
    """目标定位（上下文面板，设计 §1.2）：symbol@path:line。"""

    name: str
    path: str
    line: int = 0


class FactPayload(BaseModel):
    """取证事实只读透出（F-104 七项判定结果）。"""

    key: str
    passed: bool
    evidence: str


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
    target: SymbolPayload | None = None
    facts: list[FactPayload] = Field(default_factory=list)
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


class ProjectPickResponse(BaseModel):
    """POST /project/pick 数据体：所选目录绝对路径；用户取消为空串（F-601）。"""

    path: str = ""


class ModelServiceSettings(BaseModel):
    """F-604 模型服务设置视图：api_key 恒脱敏（MUST-19，明文不进响应）。"""

    provider: str = ""
    base_url: str = ""
    api_key_masked: str = ""
    model_id: str = ""
    decider: Literal["auto", "jev", "fallback"] = "auto"
    timeout: float = 60.0
    temperature: float | None = None
    max_tokens: int | None = None


class ProcessSettings(BaseModel):
    """F-604 流程参数视图（app_settings 表持久化）。"""

    followup_soft_round_guard: int = 10
    followup_cost_budget: float = 0.0
    telemetry: bool = True


class LockedSettings(BaseModel):
    """宪法锁定项（MUST-09）：候选集上限只读下发，不接受设置修改。"""

    candidate_limit: int


class SettingsResponse(BaseModel):
    """GET/PUT /settings 数据体（T6-11）。"""

    model_service: ModelServiceSettings
    process: ProcessSettings
    locked: LockedSettings


class ModelServiceUpdate(BaseModel):
    """PUT /settings 模型段：None = 保持不变；api_key 仅作入参明文，恒不回显。"""

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    decider: Literal["auto", "jev", "fallback"] | None = None
    timeout: float | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, gt=0)


class ProcessUpdate(BaseModel):
    """PUT /settings 流程段：None = 保持不变。"""

    followup_soft_round_guard: int | None = Field(default=None, ge=1)
    followup_cost_budget: float | None = Field(default=None, ge=0)
    telemetry: bool | None = None


class SettingsUpdate(BaseModel):
    """PUT /settings 请求体（T6-11）。"""

    model_service: ModelServiceUpdate | None = None
    process: ProcessUpdate | None = None


class PreferenceVectorPayload(BaseModel):
    """L3 偏好向量四维（GET/PUT /preference）。"""

    detail_level: float
    include_diff: float
    specify_tests: float
    max_files_norm: float


class PreferenceUpdateRequest(BaseModel):
    """PUT /preference 部分更新：None = 保持不变；超界值由后端 clip01 截断而非拒绝。"""

    detail_level: float | None = None
    include_diff: float | None = None
    specify_tests: float | None = None
    max_files_norm: float | None = None


class HistoryItemPayload(BaseModel):
    """GET /history 会话摘要（脱敏：无原句明文，MUST-19）。

    title：自定义标题优先，否则原句截断（≤40）；pinned：置顶标记（排序优先级）。
    project_root：项目全路径（供「复制项目路径」）；project 为其 basename。
    """

    session_id: str
    state: str
    project: str
    updated_at: str
    title: str = ""
    pinned: bool = False
    project_root: str = ""


class HistoryUpdateRequest(BaseModel):
    """PATCH /history/{session_id} 请求体：title/pinned 至少一项非 None（None = 保持不变）。"""

    title: str | None = None
    pinned: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> HistoryUpdateRequest:
        if self.title is None and self.pinned is None:
            raise ValueError("title 与 pinned 至少提供一项")
        return self


class AdoptionsClearResponse(BaseModel):
    """DELETE /preference/adoptions 数据体（D-6F-4）：清空条数。"""

    cleared: int


class ApiResponse(BaseModel, Generic[DataT]):
    """统一响应信封：code=0 成功；非 0 为架构文档 §3.3 错误码。"""

    code: int = 0
    message: str = "ok"
    data: DataT | None = None
    request_id: str = ""
