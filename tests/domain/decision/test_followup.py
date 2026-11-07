"""反问编排测试（2026-10-22：答案键 = question 原文，问题来自 AskUserQuestion 工具调用）。"""

from __future__ import annotations

from typing import Literal

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.followup import (
    DESIGN_REASON,
    EXECUTION_REASON,
    MAX_QUESTIONS,
    GuardrailState,
    answered_headers,
    build_unknowns,
    lint_questions,
)
from devprompt_ai.domain.decision.port import AskOption, AskQuestion, FactProbeOutput


def _ask(
    question: str,
    *,
    header: str = "范围",
    options: list[AskOption] | None = None,
    multi: bool = False,
) -> AskQuestion:
    return AskQuestion(
        key="",
        question=question,
        header=header,
        options=options or [AskOption(label="选项一", description="说明")],
        multi_select=multi,
    )


def _probe(
    questions: list[AskQuestion] | None = None,
    *,
    task_kind: Literal["design", "execution"] = "execution",
) -> FactProbeOutput:
    return FactProbeOutput(
        judgments=[],
        overall_confidence=0.0,
        questions=questions or [],
        task_kind=task_kind,
    )


class TestBuildUnknowns:
    def test_answer_key_is_question_text(self) -> None:
        items = build_unknowns(_probe([_ask("导出入口放哪里?")]), [])

        assert len(items) == 1
        assert items[0].key == "导出入口放哪里?"
        assert items[0].ask == "导出入口放哪里?"

    def test_payload_passes_through(self) -> None:
        question = _ask(
            "要覆盖哪些状态?",
            header="状态",
            options=[
                AskOption(label="hover", description="悬停"),
                AskOption(label="focus", description="聚焦"),
            ],
            multi=True,
        )

        item = build_unknowns(_probe([question]), [])[0]

        assert item.header == "状态"
        assert [o.label for o in item.options] == ["hover", "focus"]
        assert item.options[0].description == "悬停"
        assert item.multi_select is True

    def test_no_questions_means_no_asking(self) -> None:
        assert build_unknowns(_probe(), []) == []

    def test_answered_question_is_skipped(self) -> None:
        probe = _probe([_ask("入口在哪?"), _ask("要补测试吗?")])

        items = build_unknowns(probe, [], clarifications={"入口在哪?": "工具栏"})

        assert [i.key for i in items] == ["要补测试吗?"]

    def test_duplicate_question_kept_once(self) -> None:
        probe = _probe([_ask("入口在哪?"), _ask("入口在哪?")])
        assert [i.key for i in build_unknowns(probe, [])] == ["入口在哪?"]

    def test_truncates_to_max_questions(self) -> None:
        probe = _probe([_ask(f"问题{i}?") for i in range(7)])
        items = build_unknowns(probe, [])
        assert len(items) == MAX_QUESTIONS
        assert [i.key for i in items] == [f"问题{i}?" for i in range(MAX_QUESTIONS)]

    def test_reason_depends_on_task_kind(self) -> None:
        assert (
            build_unknowns(_probe([_ask("q?")], task_kind="design"), [])[0].reason == DESIGN_REASON
        )
        assert (
            build_unknowns(_probe([_ask("q?")], task_kind="execution"), [])[0].reason
            == EXECUTION_REASON
        )

    def test_blank_question_is_dropped(self) -> None:
        assert build_unknowns(_probe([_ask("   ")]), []) == []

    def test_answered_question_matched_after_normalization(self) -> None:
        """改写标点/空格不算新问题（2026-11-03）。"""
        probe = _probe([_ask("红色的落地方式选哪种？"), _ask("要补测试吗?")])

        items = build_unknowns(probe, [], clarifications={"红色的落地方式 选哪种?": "新增主题变量"})

        assert [i.key for i in items] == ["要补测试吗?"]

    def test_answered_header_skips_same_topic(self) -> None:
        """同 header + 同一件事（措辞接近）仍跳过：模型改写标点时靠这一层兜住。"""
        probe = _probe(
            [
                _ask("按钮悬停色要不要一起改?", header="状态覆盖"),
                _ask("导出放哪?", header="范围"),
            ]
        )

        items = build_unknowns(
            probe, [], answered_header_asks={"状态覆盖": ["按钮悬停色需要一起改吗"]}
        )

        assert [i.key for i in items] == ["导出放哪?"]

    def test_same_header_new_question_is_kept(self) -> None:
        """同 header 下的**新**问题不能整类吞掉（2026-11-07 修 shortcut）。"""
        probe = _probe([_ask("重连次数上限取几次?", header="范围")])

        items = build_unknowns(probe, [], answered_header_asks={"范围": ["允许修改测试文件吗"]})

        assert [i.key for i in items] == ["重连次数上限取几次?"]

    def test_answered_headers_maps_header_to_answered_asks(self) -> None:
        """header → 已答问题归一文本，供上面两条规则区分「改措辞」与「新问题」。"""
        headers = answered_headers(
            {"允许改测试吗": "可以"},
            [{"ask": "允许改测试吗?", "header": "范围"}, {"ask": "还没答的", "header": "风险"}],
        )

        assert headers == {"范围": frozenset({"允许改测试吗"})}


class TestLintQuestions:
    """形态合规检查：只报告不修改（用户 2026-10-20 裁定），且不含原文（MUST-19）。"""

    def test_compliant_question_has_no_issue(self) -> None:
        question = AskQuestion(
            key="",
            question="导出入口放哪里?",
            header="入口",
            options=[
                AskOption(label="工具栏", description="更显眼，占用工具栏空间"),
                AskOption(label="页面右上", description="不占工具栏，需滚动到底部"),
            ],
        )
        assert lint_questions([question]) == []

    def test_reports_shape_violations(self) -> None:
        question = AskQuestion(
            key="",
            question="导出入口放哪里",
            header="这是一个超过十二字符的短标签",
            options=[AskOption(label="唯一的选项名称太长了", description="说明")],
        )
        issues = lint_questions([question])
        assert "q0.question_no_mark" in issues
        assert "q0.header_too_long" in issues
        assert "q0.options_count" in issues
        assert "q0.label_too_long" in issues

    def test_reports_forbidden_punctuation(self) -> None:
        question = AskQuestion(
            key="",
            question="选哪个?",
            header="方案",
            options=[
                AskOption(label="方案A(旧)", description="以括号标注"),
                AskOption(label="方案B", description="推荐, 但成本高"),
            ],
        )
        issues = lint_questions([question])
        assert "q0.halfwidth_paren" in issues
        assert "q0.comma_space" in issues

    def test_issue_codes_contain_no_model_text(self) -> None:
        question = AskQuestion(
            key="",
            question="含敏感路径 D:/secret 的问题",
            header="x",
            options=[AskOption(label="a", description="b")],
        )
        assert all("secret" not in issue for issue in lint_questions([question]))


class TestGuardrail:
    def test_round_trigger(self) -> None:
        cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
        assert GuardrailState(rounds=10).should_trigger(cfg) is True
        assert GuardrailState(rounds=9).should_trigger(cfg) is False

    def test_cost_trigger_and_zero_disabled(self) -> None:
        cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
        assert GuardrailState(rounds=0, cost_tokens=5000).should_trigger(cfg) is False
        rich = AppConfig(_env_file=None, followup_cost_budget=1000.0)  # type: ignore[call-arg]
        assert GuardrailState(rounds=0, cost_tokens=1000).should_trigger(rich) is True

    def test_cost_budget_enabled_by_default(self) -> None:
        """2026-11-05：成本护栏随默认配置启用（此前默认 0 = 禁用）。"""
        cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
        assert cfg.followup_cost_budget > 0
        budget = int(cfg.followup_cost_budget)
        assert GuardrailState(rounds=0, cost_tokens=budget).should_trigger(cfg) is True
        assert GuardrailState(rounds=0, cost_tokens=budget - 1).should_trigger(cfg) is False

    def test_reset(self) -> None:
        state = GuardrailState(rounds=10)
        state.reset()
        assert state.rounds == 0
