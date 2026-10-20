"""Web 契约模型（Pydantic v2，XxxRequest/XxxResponse 命名）。

错误响应仅含 code + message + request_id，不回传堆栈（MUST-19）。
ApiResponse 泛型化：data 体类型进 OpenAPI，供前端类型生成精确对齐（F-705）。
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

DataT = TypeVar("DataT")


class OptimizeRequest(BaseModel):
    """POST /optimize 请求体（该端点有副作用，客户端禁重试，MUST-15）。

    ``session_id`` 非空表示在同一会话开启新一轮（多轮，2026-10-20）；为空则新建会话。
    """

    sentence: str
    #: 第二轮起可留空——后端沿用该会话既有的 project_root
    project: str = ""
    session_id: str | None = None


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


class TurnSummaryPayload(BaseModel):
    """多轮轮次摘要（GET /history/{session_id}/turns）：不含原句与方案正文。"""

    turn_id: str
    turn_index: int
    state: str
    target: str = ""
    conclusion: str = ""
    open_items: list[str] = Field(default_factory=list)
    created_at: str = ""


class TurnDetailPayload(TurnSummaryPayload):
    """单轮详情（GET /turns/{turn_id}）：正文懒加载，仅在用户展开时拉取。"""

    input: str = ""
    variants: list[VariantPayload] = Field(default_factory=list)
    facts: list[FactPayload] = Field(default_factory=list)


class AskOptionPayload(BaseModel):
    """反问选项（对齐 CodeBuddy SDK AskUserQuestion 的 options[]）。"""

    label: str
    description: str = ""


class UnknownItemPayload(BaseModel):
    """domain UnknownItem 的契约镜像（仅渲染字段）。

    2026-10-20：新增 header / options / multi_select，使反问形态对齐官方
    AskUserQuestion；``key`` 仍为答案键（clarifications 去重依赖它）。
    """

    key: str
    reason: str
    best_guess: str
    ask: str
    header: str = ""
    options: list[AskOptionPayload] = Field(default_factory=list)
    multi_select: bool = False


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
    2026-10-18 移除 `label`（显示名称）——界面一律直接展示 `model_id`；
    同日**供应商中心化重构（BREAKING）**：`base_url` / `api_key_masked` 移到
    `ProviderConfigView`（一个端点一份密钥），条目改为经 `provider_id` 引用供应商。
    """

    id: str
    provider_id: str
    #: 厂商 key（由 provider_id 解析而来，供能力兜底与展示；非用户可填）
    provider: str
    model_id: str
    is_active: bool
    capabilities: ModelCapabilitiesView = Field(default_factory=ModelCapabilitiesView)
    # 2026-09-17 多供应商扩展：`api_mode` 为空表示按 provider 默认推断；
    # `reasoning_effort` / `max_context_length` 是**每条目可覆盖**的（缺省沿用 provider 默认）。
    # `max_context_length` 只能取 `providers[].context_window_tiers` 里的档位值——
    # 自由填数会让用户得到「我填了 1M 但实际只有 200K」的假安全感。
    api_mode: str | None = None
    reasoning_effort: str | None = None
    max_context_length: int | None = None


class ProviderConfigView(BaseModel):
    """供应商配置脱敏视图（2026-10-18 供应商中心化重构新增）。

    端点与密钥**只存一份**：`base_url` + `api_key` 配一次，该供应商下所有模型条目共用。
    `api_key` 恒脱敏回显，绝不回传明文（MUST-19）。
    """

    id: str
    provider: str
    base_url: str
    api_key_masked: str


class ProviderConfigUpdate(BaseModel):
    """PUT /settings providers 段条目：`id` 缺省为新增（后端生成 ``p-`` + uuid8）。

    **权威列表语义**：本次未出现的既有供应商记录一律删除，其下模型条目随 `models`
    整表替换一并消失（用户裁定的级联删除）。`api_key` 空值/None = 沿用同 id 旧值，
    与 `ModelEntryUpdate` 的密钥语义一致——前端只有脱敏值，不会回传明文（MUST-19）。
    """

    id: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class ModelEntryUpdate(BaseModel):
    """PUT /settings models 段条目：id=None 为新增（后端生成）；按 `provider_id` 引用供应商。

    2026-09-17 多供应商扩展。`None`/省略 = 沿用同 id 旧值；显式传值即覆盖。
    2026-10-18 **BREAKING**：移除 `label`（显示名称）、`base_url`、`api_key` 与
    `inherit_api_key_from`——端点与密钥已上移到 `providers` 段，一个端点只配一次。
    """

    id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
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


class ModelDirectoryEntry(BaseModel):
    """模型目录条目（2026-10-17 窗口/能力下沉到模型级）。

    同厂商不同模型的窗口可能不同，厂商级单值表达不了，故模型单独成条。

    - `max_context_length` 为 `None` = 该模型窗口**未登记**，前端不展示、告警不触发
      （查证不到时如实留空，禁填占位默认值）。
    - `context_window_tiers` 是该模型可单选的档位集合（升序）；空 = 只能用标称值。
    - `reasoning_efforts` 是该模型官方给出的思考强度档位（**按模型粒度，各模型不可
      共用一份清单**）；空 = 厂商未提供，前端不展示该段而不是编造选项。
    - `default_effort` 是官方标注的默认强度；空 = 取第一档。
    """

    model_id: str
    label: str
    max_context_length: int | None = None
    context_window_tiers: list[int] = Field(default_factory=list)
    reasoning_efforts: list[str] = Field(default_factory=list)
    default_effort: str = ""


class ProviderDirectoryEntry(BaseModel):
    """provider 目录条目（2026-09-17 多供应商扩展）。

    前端据此渲染 provider 下拉与动态表单：`base_url` 为空表示**官方端点未登记**
    （逐个查证不到时如实留空），UI 须提示用户自行查询文档填写，不得编造。

    ``max_context_length`` 是**厂商标称输入窗口**，查证不到时为 ``None``（未登记）——
    填占位默认值会让 UI 拿一个不存在的上限做告警判定，比不显示更糟。

    ``context_window_tiers`` 是用户可单选的**档位集合**（绝对 token，升序）：
    - 空数组 = 该厂商只有标称默认值、不可选（UI 只显示默认档）；
    - 每个档位都必须是厂商真实支持的规格，且不得大于 ``max_context_length``。

    ``models`` 是该厂商**已核实**的模型目录（2026-10-17）；空数组表示未登记，
    此时前端回落用厂商级的窗口与档位。
    """

    id: str
    label: str
    base_url: str = ""
    needs_key: bool = True
    default_api_mode: str = "chat_completions"
    supported_api_modes: list[str] = Field(default_factory=lambda: ["chat_completions"])
    max_context_length: int | None = None
    context_window_tiers: list[int] = Field(default_factory=list)
    models: list[ModelDirectoryEntry] = Field(default_factory=list)
    supports_reasoning: bool = False
    quirks: str = ""


class ModelCatalogItem(BaseModel):
    """模型目录条目（契约 ModelCatalogItem）：下拉里的一个选项。

    - `source` = `remote` 表示窗口来自端点实时返回；`static` 表示来自静态表兜底。
    - `reasoning_efforts` = 该端点给出的推理强度档位（**按模型粒度**，各模型相互独立，
      不可共用一份通用清单）；空数组 = 厂商未提供，前端不展示该项而不是编造选项。
    - `is_stale` = 该模型已配置但不在当前列表中（厂商下架 / 中转站隐藏），
      存量配置不失效，仅在下拉里标注。
    """

    model_id: str
    label: str
    max_context_length: int | None = None
    context_window_tiers: list[int] = Field(default_factory=list)
    reasoning_efforts: list[str] = Field(default_factory=list)
    source: Literal["remote", "static"] = "remote"
    is_stale: bool = False


class ModelCatalogRefreshRequest(BaseModel):
    """刷新模型列表请求体。

    2026-10-18 **BREAKING**：`entry_id` → `provider_id`。刚配好、还没勾选任何模型的
    供应商也必须能刷新（否则多选列表永远是空的），而它此时没有任何条目可依。

    **不含 api_key**——密钥只从 settings.json（0600）按 `provider_id` 取，
    明文密钥绝不进请求体与日志（MUST-19）。
    """

    provider_id: str = Field(min_length=1)


class ModelCatalogResponse(BaseModel):
    """模型目录读取 / 刷新响应。

    ``warning`` 非空表示本次刷新失败、``models`` 是**上次落库的结果**
    （或静态表兜底）——刷新失败不清空已配模型。
    """

    provider: str
    base_url: str
    fetched_at: str | None = None
    models: list[ModelCatalogItem] = Field(default_factory=list)
    warning: str | None = None


class SettingsResponse(BaseModel):
    """GET/PUT /settings 数据体（T6-11）。

    ``models`` 为多模型注册表脱敏视图（F-604，2026-10-13）；字段无默认值（响应必有值）。

    2026-09-17 迁移增 ``providers`` 目录（provider 下拉与窗口档位的数据源）。
    **复用本端点下发而非新增路径**，故契约仍 13 路径 / 16 操作。
    同日移除 ``model_specs``（参数编辑区已下线）。
    2026-10-18 供应商中心化重构新增 ``provider_configs`` 段（**用户自己配置的供应商**：
    端点 + 密钥，一个端点一份）。注意与上面的 ``providers`` **目录段**是两回事：
    前者是静态厂商目录（只读、下拉数据源），后者是用户凭据配置（可写）。
    """

    models: list[ModelEntryView]
    provider_configs: list[ProviderConfigView] = Field(default_factory=list)
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

    1. ``provider_configs`` —— **权威列表**（2026-10-18 供应商中心化重构新增）。
       数组内以 ``id`` 匹配既有供应商：缺 ``id`` 视为新增（后端生成 ``p-`` + uuid8）；
       **未出现的既有供应商视为删除**，其下模型条目随 ``models`` 整表替换一并消失
       （级联删除，用户裁定）。``ProviderConfigUpdate.api_key`` 空值或 ``None``
       表示**沿用同 id 的旧值**（前端只有脱敏值，不会回传明文，MUST-19）。
       传 ``None`` 表示不动供应商段。
    2. ``models`` —— **整表替换**。数组内以 ``id`` 匹配既有条目：缺 ``id`` 视为新增
       （后端生成）；**列表中未出现的既有条目视为删除**。传 ``None`` 表示不动注册表。
       条目经 ``provider_id`` 引用供应商（2026-10-18 起端点与密钥不再挂在条目上）。
    3. 其他顶层键 —— ``None`` 表示保持不变（逐键更新，非整体替换）。

    ``active_model_id`` 切换当前生效条目（切换后该条目整体镜像进 model_service，
    由 service 层执行）。
    """

    provider_configs: list[ProviderConfigUpdate] | None = None
    models: list[ModelEntryUpdate] | None = None
    active_model_id: str | None = None
    model_service: ModelServiceUpdate | None = None
    process: ProcessUpdate | None = None


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


class ApiResponse(BaseModel, Generic[DataT]):
    """统一响应信封：code=0 成功；非 0 为架构文档 §3.3 错误码。"""

    code: int = 0
    message: str = "ok"
    data: DataT | None = None
    request_id: str = ""
