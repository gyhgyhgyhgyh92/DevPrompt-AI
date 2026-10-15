"""F-003 配置管理测试：默认值、环境覆盖、热重载、权重校验。"""

from pathlib import Path

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import ConfigurationError

# mypy 的 dataclass_transform 不识别 pydantic-settings 注入的 _env_file 形参（生态已知限制），
# 故下文 AppConfig(_env_file=None) 均标注 type: ignore[call-arg]（计划代码 × mypy 冲突的最小修复）。


def test_defaults_match_f003() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert cfg.prefer_adapt_weight == 0.6
    assert cfg.prefer_history_weight == 0.4
    assert cfg.prefer_hard_threshold == 0.5
    assert cfg.prefer_soft_threshold == 0.12
    assert cfg.prefer_min_confidence == 0.6
    assert cfg.prefer_low_confidence == 0.4
    assert cfg.followup_soft_round_guard == 10
    assert cfg.followup_cost_budget == 0.0  # 0 = 禁用成本护栏
    assert cfg.db_path == "~/.devprompt-ai/devprompt.db"
    assert cfg.fact_probe_threshold == 0.75
    assert cfg.max_state_tokens == 30000
    # F-604 新键（T6-11）：模型调用参数 + 遥测
    assert cfg.llm_timeout == 60.0
    assert cfg.llm_temperature is None
    assert cfg.llm_max_tokens is None
    assert cfg.telemetry is True


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREFER_ADAPT_WEIGHT", "0.7")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert cfg.prefer_adapt_weight == 0.7
    assert cfg.llm_base_url == "https://api.deepseek.com/v1"


def test_hot_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert cfg.prefer_adapt_weight == 0.6
    monkeypatch.setenv("PREFER_ADAPT_WEIGHT", "0.65")
    cfg.reload()
    assert cfg.prefer_adapt_weight == 0.65  # 无需重启即生效（F-003 行为列）


def test_weights_must_sum_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREFER_ADAPT_WEIGHT", "0.7")
    monkeypatch.setenv("PREFER_HISTORY_WEIGHT", "0.4")
    with pytest.raises(ConfigurationError) as exc_info:
        AppConfig(_env_file=None).validate()  # type: ignore[call-arg]
    assert exc_info.value.code == 9002  # 权重配错给明确错误（F-003 验收）


def test_validate_passes_on_defaults() -> None:
    AppConfig(_env_file=None).validate()  # type: ignore[call-arg]  # 不抛即过


# ---------- 本地设置加载链（T6-11：init > env > 本地设置 > .env > 默认值） ----------


def test_local_settings_merged_below_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """本地设置补默认缺口；环境变量仍优先于本地设置（MUST-19 修订后语义）。

    分段存储：模型段在 settings.json，流程段在 app_settings 表（F-604）。
    """
    import json

    from devprompt_ai.memory.settings_store import write_process_settings

    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"model_service": {"base_url": "https://from-file", "model_id": "file-model"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    write_process_settings({"followup_soft_round_guard": 8})
    monkeypatch.setenv("LLM_BASE_URL", "https://from-env")

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert cfg.llm_base_url == "https://from-env"  # env > 本地设置
    assert cfg.llm_model == "file-model"  # 本地设置 > 默认值
    assert cfg.followup_soft_round_guard == 8  # 流程参数经 app_settings 表生效


def test_local_process_settings_from_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """流程参数经 app_settings 表进入加载链（JSON 值类型还原）。"""
    from devprompt_ai.memory.settings_store import write_process_settings

    db = tmp_path / "settings.db"
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(db))
    write_process_settings({"telemetry": False, "followup_cost_budget": 12.5})

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert cfg.telemetry is False
    assert cfg.followup_cost_budget == 12.5
