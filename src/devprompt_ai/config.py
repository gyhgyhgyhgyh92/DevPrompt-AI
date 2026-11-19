"""F-003 配置管理：Pydantic Settings，加载链 init > 环境变量 > 本地设置 > .env > 默认值。

MUST-19 修订后语义（真源 §13 2026-10-12 批准）：环境变量优先；密钥不入库、不进日志——
本地设置文件 settings.json（0600）为密钥唯一落盘处，app_settings 表存流程参数。
键集 = F-003 的 14 项 + 架构文档 §1.6 运行时组 + F-604 设置项；权重/阈值支持热重载（reload）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from devprompt_ai.common.envhint import ENV_PURPOSE
from devprompt_ai.domain.context.budget import state_budget_for_window
from devprompt_ai.domain.model_spec import (
    CONTEXT_ALERT_RATIO,
    NATIVE_PARAMETERS,
    apply_provider_constraints,
    context_window_alert,
    is_value_empty,
    max_context_length_of,
    resolve_api_mode,
)

# settings.json model_service 段键 → AppConfig 字段名（F-604 契约键与配置键分离）
MODEL_KEY_MAP: dict[str, str] = {
    "provider": "llm_provider",
    "base_url": "llm_base_url",
    "api_key": "llm_api_key",
    "model_id": "llm_model",
    "timeout": "llm_timeout",
    "temperature": "llm_temperature",
    "max_tokens": "llm_max_tokens",
    "llm_params": "llm_params",  # 生效模型的参数覆盖（2026-09-17 迁移）
    "api_mode": "api_mode",  # 生效模型的 API 形态（2026-09-17 多供应商扩展）
    # 条目级上下文窗口覆盖；0 = 沿用全局 context_window_tokens。
    # 2026-11-10 起用于请求预算与压缩阈值（仍不硬截断本轮取证，MUST-25）
    "max_context_length": "max_context_length",
}


class _LocalSettingsSource(PydanticBaseSettingsSource):
    """本地设置合并源（MUST-19 修订后）：settings.json 模型段 + app_settings 流程段。

    优先级低于环境变量、高于 .env（对应加载链第三级）；缺失静默跳过。
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # 本源整体经 __call__ 提供，单键查询不参与

    def __call__(self) -> dict[str, Any]:
        from devprompt_ai.memory.settings_store import load_local_settings

        local = load_local_settings()
        values: dict[str, Any] = {}
        for src_key, dst_key in MODEL_KEY_MAP.items():
            if src_key in local.get("model_service", {}):
                values[dst_key] = local["model_service"][src_key]
        for key in ("followup_soft_round_guard", "followup_cost_budget", "telemetry"):
            if key in local.get("process", {}):
                values[key] = local["process"][key]
        # 可观测性三模块开关（2026-11-12）：与流程段同表持久化，重启后按上次保存值装配
        for key in (
            "obs_trace_enabled",
            "obs_trace_retention_days",
            "obs_metrics_enabled",
            "obs_replay_enabled",
        ):
            if key in local.get("process", {}):
                values[key] = local["process"][key]
        return values


class AppConfig(BaseSettings):
    llm_provider: str = ""  # F-604 供应商标识（UI 分段展示用；URL 预填由前端映射）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    # F-604 模型服务调用参数（T6-11）：大 prompt 调用超时；温度/max_tokens 未设不下发
    llm_timeout: float = 60.0
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    # 生效模型的参数覆盖（2026-09-17 模型管理迁移，裁定 D3「每模型独立参数」）：
    # 由 service 在激活条目时从 `param_overrides` 清洗后镜像进 model_service 段的
    # `llm_params` 键。刻意**不让 AppConfig 直接读注册表**——config 依赖 memory 会
    # 把「配置」变成「有状态的存储读取者」，且与既有镜像机制重复。
    llm_params: dict[str, Any] = Field(default_factory=dict)
    # 生效模型的 API 形态（2026-09-17 多供应商扩展）。空串 = 用 provider 默认；
    # 由 service 在激活条目时从该条目的 api_mode 镜像而来（与 llm_params 同机制）。
    # 取值见 domain/model_spec.ApiMode：chat_completions / responses /
    # anthropic_messages / gemini_generate_content。
    api_mode: str = ""
    # 生效条目的上下文窗口覆盖（0 = 沿用 provider 默认）。仅用于**告警**，
    # 不做截断——截断检索证据会削弱召回率，直接触碰 MUST-25 硬门禁。
    max_context_length: int = 0

    prefer_hard_threshold: float = 0.5
    prefer_soft_threshold: float = 0.12
    prefer_min_confidence: float = 0.6
    prefer_low_confidence: float = 0.4

    followup_soft_round_guard: int = 10
    #: 单流程 LLM token 总数上限；0 = 禁用（MUST-26 成本软护栏）。
    #: 结构推导（2026-11-06）：轮次护栏 10 × 单轮 token 上界 5000 = 50000。
    #: 单轮上界取首批真实样本 p95（3.6k）向上取整——护栏是「成本异常时的兜底闸」，
    #: 不替代轮次护栏；正常 8~10 轮的累计消耗仍在阈值内，只有单轮异常膨胀才会先撞线。
    followup_cost_budget: float = 50_000.0
    #: 断言对账严格模式（2026-11-05）：C 档要求模型至少声明一条引用，
    #: 一条都没声明时降为 B。默认关闭——先观察真实会话的声明率，再决定是否收紧。
    # 2026-11-07 BREAKING：未声明 claims 默认参与门禁（旧默认 False 让「一条都不声明」免检）。
    claim_strict: bool = True
    telemetry: bool = True  # F-604 遥测开关（T6-11）：关闭后固定事件不落盘

    # SQLite 单文件（L1/L3；用户主目录 ~ 由 expanduser 解析，展开归 4B init_schema）
    db_path: str = "~/.devprompt-ai/devprompt.db"
    # F5 单写者锁（2026-11-07）：多进程写同一库会把运行中会话写成假中断。
    # 心跳失联超过 stale 秒视为崩溃遗留，可被新进程接管。
    single_writer_lock: bool = True
    writer_lock_stale_seconds: float = 120.0
    # 流内超时分层（A10）：探针/排序用短超时快速失败，生成用长超时。
    llm_probe_timeout: float = 30.0
    llm_rank_timeout: float = 30.0
    llm_generate_timeout: float = 120.0
    # 生成阶段同轮工具回路（2026-11-18）：>1 时允许模型在生成方案时自主调用
    # search_code 补充检索，SDK 执行工具并把结果回喂同一轮；=1 关闭（行为与旧版一致）。
    generate_tool_turns: int = 3
    # 看门狗（A9）：单次 run 的硬上限；超时以 watchdog-stall 收尾。
    run_timeout_seconds: float = 900.0
    # 上下文窗口（用于压缩档位与相位收敛的轮次门槛）；默认按 1M 模型保守取值。
    context_window_tokens: int = 1_000_000
    # 仓库符号图（⑤）：首次检索会扫全仓 Python 文件，默认关闭；在自己的项目上实测后再开。
    repo_graph_enabled: bool = False
    # 认知账本（B15）：每轮注入只读状态快照；默认关闭，实测后再开。
    context_ledger_enabled: bool = False
    # 多模型路由（G2–G6）：按 purpose 从 settings 注册表选模型，bandit 在线学习，
    # 失败按注册顺序主备切换。候选 ≤1 时自动退化为现状路径（行为对等）。
    #: 多候选链（2026-11-15 用户裁定）：默认关闭随机/胜率择优——模型只由用户在设置中的
    #: 显式选择决定（激活条目 → 首个可用），其余条目仅作固定顺序 failover。
    multi_model_routing: bool = False
    # B11 LLM 摘要：压缩触发时把被丢弃的历史段交给 cheap 槽摘要；失败回退确定性 handoff。
    # 默认关闭——每次压缩多一次 LLM 调用，实测摘要质量优于 80 字规则摘要后再开。
    summary_llm_enabled: bool = False
    # B1–B4 增量附录（<context-update>）：关闭则不发增量（恢复改造前行为）。
    context_layers_enabled: bool = True
    # C1–C5 工具输出治理：关闭则动作卡片退回 20 行/2000 字符旧截断口径。
    tool_output_governance: bool = True
    # K6 team 编排：关闭则委派走单工单直连调度闸（不按波分派）。
    team_orchestration: bool = True
    # ---- 可观测性三模块（2026-11-12，独立启用/配置）----
    obs_trace_enabled: bool = True
    obs_trace_retention_days: int = 30
    obs_trace_full_payload: bool = True
    obs_metrics_enabled: bool = True
    obs_metrics_p95_warn_ms: int = 5000
    obs_metrics_error_rate_warn: float = 0.2
    obs_metrics_token_warn: int = 50000
    obs_metrics_tool_failure_warn: float = 0.2
    obs_metrics_refusal_warn: float = 0.2
    obs_metrics_alert_cooldown_s: int = 300
    obs_metrics_critical_multiplier: float = 2.0
    obs_replay_enabled: bool = True
    obs_replay_max_nodes: int = 20000
    obs_replay_timeout_seconds: float = 120.0
    #: 多轮 Query 改写走 LLM 结构化改写（2026-11-19）：默认开，失败自动回退规则。
    query_rewrite_llm: bool = True
    fact_probe_threshold: float = 0.75
    max_state_tokens: int = 30000  # 上下文装配预算下限（随档位放大，上限 160K）

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_dir: str = "./.logs"
    data_dir: str = "~/.devprompt-ai"
    cors_origins: str = "http://localhost:5173"

    # 优先级（MUST-19 修订后）：init > 进程环境变量 > 本地设置（settings.json + app_settings）
    # > .env 文件 > 默认值；.env 与本地设置不入库（MUST-23）
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """插入本地设置源：环境变量之下、.env 之上（加载链第三级）。"""
        return (
            init_settings,
            env_settings,
            _LocalSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # 签名冻结（计划 §6.3 接口标准）：与 pydantic BaseModel.validate（classmethod）语义不同，非重写
    def validate(self) -> None:  # type: ignore[override]
        """权重之和必须为 1.0，否则明确报错（F-003 行为列，9002）。

        **不校验 LLM 三项**：本地工具允许先启动再配模型（用户 2026-10-16 裁定，
        恢复 F-003 的「默认配置可通过」契约）。LLM 配置缺失由 `GET /health` 的
        `llm_config` 项报告——见 `interfaces/api/health.py`。
        """

    def effective_llm_params(self) -> dict[str, Any]:
        """本次调用实际生效的采样参数（可直接展开进 `ModelSettings`）。

        合并链（后者覆盖前者）：
            1. 全局默认 `llm_temperature` / `llm_max_tokens`（设置中心或 .env）；
            2. 当前生效模型的 `param_overrides`（每模型独立，裁定 D3）。

        最后经 `apply_provider_constraints` 按厂商剔除不支持项——例如 Anthropic
        不接受 temperature，剔除后才不会发出会报错的请求。

        只返回 `ModelSettings` 原生支持的键（见 `NATIVE_PARAMETERS`）；未设值的键不出现在
        结果里，交由供应商使用自己的默认值。**本方法不读注册表**——调用方（harness）
        拿到的 `AppConfig` 已是激活条目镜像后的配置。
        """
        merged: dict[str, Any] = {}
        for key, value in (
            ("temperature", self.llm_temperature),
            ("max_tokens", self.llm_max_tokens),
        ):
            if value is not None:
                merged[key] = value
        # 模型级覆盖优先于全局默认（裁定 D3：每模型独立参数）
        merged.update(self.llm_params or {})
        provider = self.llm_provider or ""
        cleaned = apply_provider_constraints(provider, merged)
        # 只保留 ModelSettings 原生支持的键。`apply_provider_constraints` 会注入
        # provider 的 force_params（如 anthropic 的 reasoning_effort='high'），
        # 但该键不属于 ModelSettings 字段——pydantic 会当 extra 收下，行为不确定
        # （可能被静默忽略使 force_params 形同虚设，也可能被透传导致供应商报错）。
        # 非原生参数改走 extra_body 显式下发，见 :meth:`extra_body_params`。
        return {key: value for key, value in cleaned.items() if key in NATIVE_PARAMETERS}

    def extra_body_params(self) -> dict[str, Any]:
        """需经 `extra_body` 下发的参数（`ModelSettings` 无对应字段的那些）。

        **`reasoning_effort` 按 API 形态分流**（2026-11-10）：

        - `chat_completions`：顶层 `reasoning_effort`（OpenAI/DeepSeek 等）；
        - `responses`：`reasoning: {"effort": ...}`（Responses 官方字段形状）；
        - `anthropic_messages` / `gemini_generate_content`：仍以内部键
          `reasoning_effort` 传给原生适配器，由适配器转换为 `thinking` /
          `thinking_config` 后**消费掉**，不会原样发给供应商。

        **空值不发**：未设置时不进 extra_body，避免覆盖供应商默认。
        """
        merged: dict[str, Any] = dict(self.llm_params or {})
        provider = self.llm_provider or ""
        cleaned = apply_provider_constraints(provider, merged)
        extras = {
            key: value
            for key, value in cleaned.items()
            if key not in NATIVE_PARAMETERS and not is_value_empty(value)
        }
        effort = str(extras.pop("reasoning_effort", "") or "").strip().lower()
        if not effort:
            return extras
        api_mode = resolve_api_mode(provider, self.api_mode or "")
        if api_mode == "responses":
            extras["reasoning"] = {"effort": effort}
        else:
            extras["reasoning_effort"] = effort
        return extras

    def reasoning_effort_value(self) -> str:
        """当前生效条目的思考强度原始值（空串 = 未显式选择）。

        **不做空值→`none` 的解析**：那需要模型能力位，由 harness 的候选装配与
        service 的激活条目镜像负责（2026-11-10）。
        """
        return str((self.llm_params or {}).get("reasoning_effort", "") or "")

    def runtime_window(self) -> int:
        """运行时上下文窗口：条目档位优先，未登记回落全局窗口。

        2026-11-10 起真正参与请求预算与压缩阈值；它**不发给供应商**（各协议都没有
        标准的「本次请求窗口」字段），也不硬截断本轮取证（MUST-25）。
        """
        if isinstance(self.max_context_length, int) and self.max_context_length > 0:
            return self.max_context_length
        return int(self.context_window_tokens)

    def runtime_state_budget(self) -> int:
        """上下文装配总预算：随档位缩放，`max_state_tokens` 为下限。

        300K→30K、600K→60K、1M→100K、2M→160K；窗口越大保留历史越多，
        token 消耗随之上升（2026-11-10）。
        """
        return state_budget_for_window(self.runtime_window(), floor=self.max_state_tokens)

    def context_window_warning(self, estimated_tokens: int) -> str | None:
        """上下文窗口告警；**不做任何截断**。

        2026-09-17 决策：只提示、不截断。截断检索证据会直接削弱候选集信息量，
        而召回率≥80% 是 MUST-25 的硬门禁——用截断换窗口会牺牲更重要的指标。
        截断若要做，须单独立项论证（已有机制见 `state.truncated` 与
        `decision/fallback._fit_state`，那是 state 侧的既有行为，与本方法无关）。

        :param estimated_tokens: 本次请求的估算 token 数
        :return: 超过比例阈值时给出可操作的中文提示；未超限或窗口未知返回 ``None``
        """
        limit = (
            self.max_context_length
            or max_context_length_of(self.llm_provider or "", self.llm_model or "")
            or self.context_window_tokens
        )
        if limit is None or not context_window_alert(estimated_tokens, limit):
            return None
        percent = round(estimated_tokens / limit * 100)
        return (
            f"本次请求估算约 {estimated_tokens} token，"
            f"达该模型上下文窗口 {limit} token 的 {percent}%"
            f"（超过 {int(CONTEXT_ALERT_RATIO * 100)}% 阈值）；"
            f"请补充组件名或缩小检索范围以减少证据量"
        )

    def llm_problems(self) -> list[tuple[str, str]]:
        """返回 LLM 三项中未配置者的 ``(变量名, 用途)`` 清单；齐备则返回空列表。

        供 `GET /health` 生成可操作提示（不抛异常——缺配置不应阻断启动）。
        """
        missing: list[tuple[str, str]] = []
        for field, env_name in (
            ("llm_base_url", "LLM_BASE_URL"),
            ("llm_api_key", "LLM_API_KEY"),
            ("llm_model", "LLM_MODEL"),
        ):
            if not str(getattr(self, field)).strip():
                missing.append((env_name, ENV_PURPOSE[env_name]))
        return missing

    def reload(self) -> None:
        """热重载：按当前环境变量重建字段值（F-003：修改阈值无需重启即生效）。

        不自动 validate（分步设计，与构造一致）：§6.1 验收要求单键注入后 reload 生效，
        权重一致性由调用方显式调用 validate()。
        """
        # mypy dataclass_transform 不识别 pydantic-settings 注入的 _env_file 形参（生态已知限制）
        fresh = AppConfig(_env_file=None)  # type: ignore[call-arg]
        for name in type(self).model_fields:
            setattr(self, name, getattr(fresh, name))
