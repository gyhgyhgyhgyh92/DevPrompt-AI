"""F-003 配置管理：Pydantic Settings，环境变量为唯一覆盖来源（MUST-19 密钥不入库）。

键集 = F-003 的 14 项 + 架构文档 §1.6 运行时组；权重/阈值支持热重载（reload）。
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from devprompt_ai.domain.errors import ConfigurationError

DeciderMode = Literal["auto", "jev", "fallback"]


class AppConfig(BaseSettings):
    typesafe_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    prefer_adapt_weight: float = 0.6
    prefer_history_weight: float = 0.4
    prefer_hard_threshold: float = 0.5
    prefer_soft_threshold: float = 0.12
    prefer_min_confidence: float = 0.6
    prefer_low_confidence: float = 0.4

    followup_soft_round_guard: int = 10
    followup_cost_budget: float = 0.0  # 单流程 LLM token 总数上限；0 = 禁用（MUST-26 软护栏）

    # SQLite 单文件（L1/L3；用户主目录 ~ 由 expanduser 解析，展开归 4B init_schema）
    db_path: str = "~/.devprompt-ai/devprompt.db"
    fact_probe_threshold: float = 0.75
    jev_model_id: str = "jev-1.13.0"
    max_state_tokens: int = 30000

    decider: DeciderMode = "auto"
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_dir: str = "./.logs"
    data_dir: str = "~/.devprompt-ai"
    cors_origins: str = "http://localhost:5173"

    # 优先级（技术栈 §4.8）：进程环境变量 > .env 文件 > 默认值；.env 不入库（MUST-23）
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
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
