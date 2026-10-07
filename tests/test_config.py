"""F-003 配置管理测试：默认值、环境覆盖、热重载、权重校验。"""

import pytest
from pydantic import ValidationError

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
    assert cfg.jev_model_id == "jev-1.13.0"  # MUST-12：禁别名
    assert cfg.max_state_tokens == 30000
    assert cfg.decider == "auto"


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


def test_decider_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECIDER", "sideways")
    with pytest.raises(ValidationError):  # pydantic 校验失败（非 Literal 成员）
        AppConfig(_env_file=None)  # type: ignore[call-arg]
