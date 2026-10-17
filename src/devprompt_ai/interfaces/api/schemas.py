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


class CostDetailPayload(BaseModel):
    """F-805 成本明细：单次优化 token 用量（LLM 实际用量）。

    llm_tokens 为 SDK 实际用量；total_tokens 即 llm_tokens 合计
    （2026-10-15 起决策层为单一 LLM 实现，用量同源）。
    """

    llm_tokens: int
    total_tokens: int
    llm_source: Literal["actual", "no_call"]


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
    cost: CostDetailPayload | None = None  # F-805 成本明细（additive，无新增契约路径）
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


class BrowseEntryPayload(BaseModel):
    """目录浏览条目：展示名 + 完整路径 + 修改时间；搜索结果附相对父路径（F-601）。"""

    name: str
    path: str
    modified_at: str | None
    rel_parent: str | None  # 搜索结果专用（直接子级为空串）；普通列举为 null


class BrowseResponse(BaseModel):
    """GET /project/browse 数据体：path="" 为驱动器列表模式（F-601）。

    字段无默认值（响应必有值）：带默认值会被 OpenAPI 标记非必填，生成的前端类型
    将含 undefined，削弱收窄（T6-2 契约管线（生成类型）无 `?` 前提）。
    """

    path: str
    # 上级目录：None=无上级（驱动器列表）；""=驱动器根（回驱动器列表）；其余=上级路径
    parent: str | None
    entries: list[BrowseEntryPayload]
    truncated: bool


class ModelServiceSettings(BaseModel):
    """F-604 模型服务设置视图：api_key 恒脱敏（MUST-19，明文不进响应）。"""

    provider: str = ""
    base_url: str = ""
    api_key_masked: str = ""
    model_id: str = ""
    timeout: float = 60.0
    temperature: float | None = None
    max_tokens: int | None = None


class ModelCapabilitiesView(BaseModel):
    """模型能力标记（2026-09-17 模型管理迁移；迁自源项目 `ModelCapabilities`）。

    仅文本模型相关三项——图像/多模态按裁定 D4 全部排除。
    """

    supports_tools: bool = True
    supports_reasoning: bool = False
    max_context_length: int | None = None


class ModelEntryView(BaseModel):
    """注册表条目脱敏视图（F-604 多模型）：api_key 恒脱敏，is_active 标记当前生效项。

    2026-09-17 迁移增 `capabilities` 只读字段（供设置中心渲染能力徽标）；
    同日移除 `param_overrides`（参数编辑区已下线）与 `model_specs` 契约段。
    """

    id: str
    label: str
    provider: str
    base_url: str
    model_id: str
    api_key_masked: str
    is_active: bool
    capabilities: ModelCapabilitiesView = Field(default_factory=ModelCapabilitiesView)
    # 2026-09-17 多供应商扩展：`api_mode` 为空表示按 provider 默认推断；
    # `reasoning_effort` / `max_context_length` 是**每条目可覆盖**的（缺省沿用 provider 默认）。
    # `max_context_length` 只能取 `providers[].context_window_tiers` 里的档位值——
    # 自由填数会让用户得到「我填了 1M 但实际只有 200K」的假安全感。
    api_mode: str | None = None
    reasoning_effort: str | None = None
    max_context_length: int | None = None


class ModelEntryUpdate(BaseModel):
    """PUT /settings models 段条目：id=None 为新增（后端生成）；api_key None/空=保留原值。

    2026-09-17 多供应商扩展。`None`/省略 = 沿用同 id 旧值；显式传值即覆盖。
    """

    id: str | None = None
    label: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model_id: str | None = None
    api_key: str | None = None
    api_mode: str | None = None
    reasoning_effort: str | None = None
    max_context_length: int | None = Field(default=None, gt=0)


class ProcessSettings(BaseModel):
    """F-604 流程参数视图（app_settings 表持久化）。"""

    followup_soft_round_guard: int = 10
    followup_cost_budget: float = 0.0
    telemetry: bool = True


class LockedSettings(BaseModel):
    """宪法锁定项（MUST-09）：候选集上限只读下发，不接受设置修改。"""

    candidate_limit: int


class ProviderDirectoryEntry(BaseModel):
    """provider 目录条目（2026-09-17 多供应商扩展）。

    前端据此渲染 provider 下拉与动态表单：`base_url` 为空表示**官方端点未登记**
    （逐个查证不到时如实留空），UI 须提示用户自行查询文档填写，不得编造。

    ``max_context_length`` 是**厂商标称输入窗口**，查证不到时为 ``None``（未登记）——
    填占位默认值会让 UI 拿一个不存在的上限做告警判定，比不显示更糟。

    ``context_window_tiers`` 是用户可单选的**档位集合**（绝对 token，升序）：
    - 空数组 = 该厂商只有标称默认值、不可选（UI 只显示默认档）；
    - 每个档位都必须是厂商真实支持的规格，且不得大于 ``max_context_length``。
    """

    id: str
    label: str
    base_url: str = ""
    needs_key: bool = True
    default_api_mode: str = "chat_completions"
    supported_api_modes: list[str] = Field(default_factory=lambda: ["chat_completions"])
    max_context_length: int | None = None
    context_window_tiers: list[int] = Field(default_factory=list)
    supports_reasoning: bool = False
    quirks: str = ""


class SettingsResponse(BaseModel):
    """GET/PUT /settings 数据体（T6-11）。

    ``models`` 为多模型注册表脱敏视图（F-604，2026-10-13）；字段无默认值（响应必有值）。

    2026-09-17 迁移增 ``providers`` 目录（provider 下拉与窗口档位的数据源）。
    **复用本端点下发而非新增路径**，故契约仍 13 路径 / 16 操作。
    同日移除 ``model_specs``（参数编辑区已下线）。
    """

    models: list[ModelEntryView]
    providers: list[ProviderDirectoryEntry] = Field(default_factory=list)
    model_service: ModelServiceSettings
    process: ProcessSettings
    locked: LockedSettings


class ModelServiceUpdate(BaseModel):
    """PUT /settings 模型段：None = 保持不变；api_key 仅作入参明文，恒不回显。"""

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    timeout: float | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, gt=0)


class ProcessUpdate(BaseModel):
    """PUT /settings 流程段：None = 保持不变。"""

    followup_soft_round_guard: int | None = Field(default=None, ge=1)
    followup_cost_budget: float | None = Field(default=None, ge=0)
    telemetry: bool | None = None


class SettingsUpdate(BaseModel):
    """PUT /settings 请求体（T6-11 + 多模型注册表 F-604）。

    **语义是「顶层 PATCH 式 + 段内 PUT 式」的混合体**（2026-10-16 显式声明）：

    1. ``models`` —— **整表替换**。数组内以 ``id`` 匹配既有条目：缺 ``id`` 视为新增
       （后端生成）；**列表中未出现的既有条目视为删除**。传 ``None`` 表示不动注册表。
    2. ``ModelEntryUpdate.api_key`` —— 空值或 ``None`` 表示**沿用同id 的旧值**
       （不覆盖、不清空）；只有显式给出的新值才落盘。
    3. 其他顶层键 —— ``None`` 表示保持不变（逐键更新，非整体替换）。

    ``active_model_id`` 切换当前生效条目（切换后该条目整体镜像进 model_service，
    由 service 层执行）。
    """

    models: list[ModelEntryUpdate] | None = None
    active_model_id: str | None = None
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
