"""F-003 配置管理：Pydantic Settings，加载链 init > 环境变量 > 本地设置 > .env > 默认值。

MUST-19 修订后语义（真源 §13 2026-10-12 批准）：环境变量优先；密钥不入库、不进日志——
本地设置文件 settings.json（0600）为密钥唯一落盘处，app_settings 表存流程参数。
键集 = F-003 的 14 项 + 架构文档 §1.6 运行时组 + F-604 设置项；权重/阈值支持热重载（reload）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from devprompt_ai.domain.errors import ConfigurationError

# settings.json model_service 段键 → AppConfig 字段名（F-604 契约键与配置键分离）
MODEL_KEY_MAP: dict[str, str] = {
    "provider": "llm_provider",
    "base_url": "llm_base_url",
    "api_key": "llm_api_key",
    "model_id": "llm_model",
    "timeout": "llm_timeout",
    "temperature": "llm_temperature",
    "max_tokens": "llm_max_tokens",
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

    prefer_adapt_weight: float = 0.6
    prefer_history_weight: float = 0.4
    prefer_hard_threshold: float = 0.5
    prefer_soft_threshold: float = 0.12
    prefer_min_confidence: float = 0.6
    prefer_low_confidence: float = 0.4

    followup_soft_round_guard: int = 10
    followup_cost_budget: float = 0.0  # 单流程 LLM token 总数上限；0 = 禁用（MUST-26 软护栏）
    telemetry: bool = True  # F-604 遥测开关（T6-11）：关闭后固定事件不落盘

    # SQLite 单文件（L1/L3；用户主目录 ~ 由 expanduser 解析，展开归 4B init_schema）
    db_path: str = "~/.devprompt-ai/devprompt.db"
    fact_probe_threshold: float = 0.75
    max_state_tokens: int = 30000

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
        """权重之和必须为 1.0，否则明确报错（F-003 行为列，9002）。"""
        total = self.prefer_adapt_weight + self.prefer_history_weight
        if abs(total - 1.0) > 1e-9:
            raise ConfigurationError(
                f"权重之和必须为 1.0，实际 {total}",
                context={
                    "prefer_adapt_weight": self.prefer_adapt_weight,
                    "prefer_history_weight": self.prefer_history_weight,
                },
            )

    def reload(self) -> None:
        """热重载：按当前环境变量重建字段值（F-003：修改阈值无需重启即生效）。

        不自动 validate（分步设计，与构造一致）：§6.1 验收要求单键注入后 reload 生效，
        权重一致性由调用方显式调用 validate()。
        """
        # mypy dataclass_transform 不识别 pydantic-settings 注入的 _env_file 形参（生态已知限制）
        fresh = AppConfig(_env_file=None)  # type: ignore[call-arg]
        for name in type(self).model_fields:
            setattr(self, name, getattr(fresh, name))
