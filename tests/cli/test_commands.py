"""F-601/F-602 CLI 测试（CliRunner + monkeypatch build_default → Fake service）。"""

import json
from dataclasses import dataclass, field

import pytest
from typer.testing import CliRunner

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.followup import UnknownItem
from devprompt_ai.domain.generate.ports import VariantDraft
from devprompt_ai.interfaces.cli.main import app

runner = CliRunner()


@dataclass(slots=True)
class FakeSnapshot:
    session_id: str = "s1"
    status: str = "ask"
    state: str = "ASKING"
    questions: list[UnknownItem] = field(
        default_factory=lambda: [
            UnknownItem(key="token_defined", reason="未找到", best_guess="", ask="用什么 token？")
        ]
    )
    cleared: list[str] = field(default_factory=list)
    variant: VariantDraft | None = None
    message: str = ""


class FakeService:
    def __init__(self) -> None:
        self.snap = FakeSnapshot()
        self.calls: list[str] = []

    async def optimize(
        self, user_id: str, project_root: str, sentence: str, *, request_id: str
    ) -> FakeSnapshot:
        self.calls.append("optimize")
        return self.snap

    async def ask_followup(
        self, user_id: str, session_id: str, answers: dict[str, str], *, request_id: str
    ) -> FakeSnapshot:
        self.calls.append("ask_followup")
        self.snap.status = "done"
        self.snap.variant = VariantDraft(title="t", body="b", changes=["c"], level="B")
        return self.snap

    async def escape(self, user_id: str, session_id: str, *, request_id: str) -> FakeSnapshot:
        self.calls.append("escape")
        self.snap.status = "done"
        self.snap.variant = VariantDraft(title="t", body="保守", changes=[], level="A")
        return self.snap

    async def guardrail_confirm(
        self, user_id: str, session_id: str, proceed: bool, *, request_id: str
    ) -> FakeSnapshot:
        self.calls.append("guardrail_confirm")
        return self.snap

    async def get_preference(self, user_id: str) -> dict[str, float]:
        return {"detail_level": 0.5}


@pytest.fixture()
def fake_service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    svc = FakeService()
    import devprompt_ai.interfaces.cli.commands as commands

    async def fake_build_default(cfg: AppConfig) -> FakeService:
        return svc

    monkeypatch.setattr(commands, "build_default", fake_build_default)
    return svc


def test_help_lists_seven_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("optimize", "web", "config", "preference", "doctor", "init"):
        assert name in result.output


def test_optimize_json_ask_then_answer(fake_service: FakeService) -> None:
    result = runner.invoke(app, ["optimize", "把提交按钮改成 primary-500", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ask"
    assert payload["questions"][0]["key"] == "token_defined"


def test_optimize_done_json(fake_service: FakeService) -> None:
    fake_service.snap.status = "done"
    fake_service.snap.variant = VariantDraft(title="t", body="b", changes=["c"], level="B")
    result = runner.invoke(app, ["optimize", "改按钮", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "done" and payload["variant"]["level"] == "B"


def test_optimize_interactive_escape(fake_service: FakeService) -> None:
    # 输入流约定：空回车 = 采用推断并继续；输入 ! = 逃生直接生成（MUST-26 ②）
    result = runner.invoke(app, ["optimize", "改提交按钮"], input="!")
    assert result.exit_code == 0
    assert "escape" in fake_service.calls


def test_config_masks_password(monkeypatch: pytest.MonkeyPatch, fake_service: FakeService) -> None:
    # 偏差：计划写 MYSQL_PASSWORD，v1.1 存储回改 SQLite 后 AppConfig 已无该字段，改用 LLM_API_KEY
    monkeypatch.setenv("LLM_API_KEY", "change-me")
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "change-me" not in result.output  # MUST-19 脱敏
    assert "******" in result.output


def test_preference_outputs_vector(fake_service: FakeService) -> None:
    result = runner.invoke(app, ["preference", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["detail_level"] == 0.5
