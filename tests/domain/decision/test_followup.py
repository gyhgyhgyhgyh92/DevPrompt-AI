"""F-203/F-204 编排逻辑测试（纯函数，Fake 注入）。

2026-10-20：反问的时机与问法改由决策层给出（对齐 CodeBuddy SDK AskUserQuestion），
本文件覆盖「模型决定不提问 / 只问部分 / 越界 key 兜底 / 截断 4 个」四条新规则。
"""

from typing import Literal

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.followup import (
    DESIGN_REASON,
    EXECUTION_REASON,
    MAX_QUESTIONS,
    GuardrailState,
    UnknownItem,
    build_unknowns,
    lint_questions,
)
from devprompt_ai.domain.decision.port import AskOption, AskQuestion, FactJudgment, FactProbeOutput
from devprompt_ai.domain.models import FactKey, FactResult

_ALL_KEYS: tuple[FactKey, ...] = (
    "target_file_exists",
    "symbol_in_file",
    "token_defined",
    "has_data_testid",
    "has_state_styles",
    "file_type_matches",
    "test_file_exists",
)


def _probe(
    *confs: float,
    questions: list[AskQuestion] | None = None,
    task_kind: Literal["design", "execution"] = "execution",
) -> FactProbeOutput:
    return FactProbeOutput(
        judgments=[
            FactJudgment(key=k, passed=c >= 0.75, confidence=c)
            for k, c in zip(_ALL_KEYS, confs, strict=True)
        ],
        overall_confidence=0.8,
        questions=questions or [],
        task_kind=task_kind,
    )


def _ask(key: str, *, header: str = "", options: list[AskOption] | None = None) -> AskQuestion:
    return AskQuestion(
        key=key,
        question=f"请确认 {key}",
        header=header,
        options=options or [],
        multi_select=False,
    )


def _facts() -> list[FactResult]:
    return [
        FactResult("target_file_exists", True, "file=src/a.tsx"),
        FactResult("symbol_in_file", True, "src/a.tsx:12:SubmitButton"),
        FactResult("token_defined", False, "未找到"),
        FactResult("has_data_testid", True, "src/a.tsx:14:data-testid"),
        FactResult("has_state_styles", True, "src/a.tsx:20::hover"),
        FactResult("file_type_matches", True, "ext=.tsx"),
        FactResult("test_file_exists", False, "未找到"),
    ]


def test_model_questions_become_unknowns() -> None:
    probe = _probe(*([0.9] * 7), questions=[_ask("token_defined"), _ask("test_file_exists")])
    items = build_unknowns(probe, _facts())
    assert [i.key for i in items] == ["token_defined", "test_file_exists"]
    assert items[0].ask != "" and items[0].reason != ""
    assert isinstance(items[0], UnknownItem)


def test_low_confidence_fact_can_be_asked() -> None:
    probe = _probe(0.9, 0.9, 0.9, 0.5, 0.9, 0.9, 0.9, questions=[_ask("has_data_testid")])
    items = build_unknowns(probe, _facts())
    assert [i.key for i in items] == ["has_data_testid"]


def test_no_questions_means_no_asking() -> None:
    """模型判定信息已够 → 本轮不问（不再按失败事实数机械追问）。"""
    items = build_unknowns(_probe(*([0.9] * 7)), _facts())
    assert items == []


def test_question_payload_passes_through() -> None:
    """header / options / multi_select 原样带给前端（对齐官方 AskUserQuestion 形态）。"""
    question = AskQuestion(
        key="test_file_exists",
        question="要新建测试文件吗？",
        header="测试",
        options=[
            AskOption(label="新建同目录", description="与被测文件同级"),
            AskOption(label="放 __tests__", description="集中存放"),
        ],
        multi_select=True,
    )
    items = build_unknowns(_probe(*([0.9] * 7), questions=[question]), _facts())
    item = items[0]
    assert item.ask == "要新建测试文件吗？"
    assert item.header == "测试"
    assert [o.label for o in item.options] == ["新建同目录", "放 __tests__"]
    assert item.options[0].description == "与被测文件同级"
    assert item.multi_select is True


def test_questions_limited_to_four() -> None:
    facts = [FactResult(k, False, "未找到") for k in _ALL_KEYS]
    probe = _probe(*([0.9] * 7), questions=[_ask(k) for k in _ALL_KEYS])
    items = build_unknowns(probe, facts)
    assert len(items) == MAX_QUESTIONS
    assert [i.key for i in items] == list(_ALL_KEYS[:MAX_QUESTIONS])


def test_question_may_ride_on_code_fact_key() -> None:
    """模型常把「按钮点击后什么行为」这类意图问题挂在 symbol_in_file 上，必须放行。

    实测 3/3 都如此；按 key 白名单过滤会误杀合法提问（2026-10-20 采样结论）。
    内容是否正确由 prompt 的提问纪律约束，不在这里用 key 判断。
    """
    probe = _probe(0.9, 0.5, 0.9, 0.9, 0.9, 0.9, 0.9, questions=[_ask("symbol_in_file")])
    items = build_unknowns(probe, _facts())
    assert [i.key for i in items] == ["symbol_in_file"]


def test_mixed_questions_keep_order() -> None:
    """模型给出的顺序即展示顺序（按重要性排序由模型负责）。"""
    probe = _probe(
        0.9,
        0.5,
        0.9,
        0.9,
        0.9,
        0.9,
        0.9,
        questions=[_ask("symbol_in_file"), _ask("test_file_exists")],
    )
    items = build_unknowns(probe, _facts())
    assert [i.key for i in items] == ["symbol_in_file", "test_file_exists"]


def _clear_facts() -> list[FactResult]:
    return [FactResult(k, True, "ok") for k in _ALL_KEYS]


def test_design_mode_asks_without_fact_gaps() -> None:
    """设计类：七项取证全过也能问——否则「加个导出」这类模糊句永远问不出来。"""
    probe = _probe(
        *([0.9] * 7),
        questions=[
            AskQuestion(key="ux", question="导出入口放在哪里?", header="入口"),
            AskQuestion(key="scope", question="导出哪些字段?", header="范围"),
        ],
        task_kind="design",
    )
    items = build_unknowns(probe, _clear_facts())
    assert [i.key for i in items] == ["ux", "scope"]
    assert items[0].reason == DESIGN_REASON
    assert items[0].ask == "导出入口放在哪里?"


def test_design_mode_respects_clarifications() -> None:
    probe = _probe(
        *([0.9] * 7),
        questions=[AskQuestion(key="ux", question="入口在哪?", header="入口")],
        task_kind="design",
    )
    items = build_unknowns(probe, _clear_facts(), clarifications={"ux": "工具栏"})
    assert items == []


def test_empty_key_is_normalized_in_design_mode() -> None:
    """空 key 归一为 q-{i}，否则去重与答案归位都会失效。"""
    probe = _probe(
        *([0.9] * 7),
        questions=[
            AskQuestion(key="", question="要支持多选吗?", header="交互"),
            AskQuestion(key="", question="失败时怎么提示?", header="失败态"),
        ],
        task_kind="design",
    )
    items = build_unknowns(probe, _clear_facts())
    assert [i.key for i in items] == ["q-0", "q-1"]


def test_over_long_fields_are_not_truncated() -> None:
    """不合规产出原样下发（用户裁定）：截断会掩盖真实违规，只由 lint 记日志。"""
    long_header = "这是一个远超十二字符的短标签"
    long_label = "这是一个很长很长很长的选项标签"
    probe = _probe(
        *([0.9] * 7),
        questions=[
            AskQuestion(
                key="ux",
                question="选哪个?",
                header=long_header,
                options=[AskOption(label=long_label, description="d")],
            )
        ],
        task_kind="design",
    )
    item = build_unknowns(probe, _clear_facts())[0]
    assert item.header == long_header
    assert item.options[0].label == long_label


def test_custom_key_is_accepted_in_execution_mode() -> None:
    """执行类闸门（范围/选型/验收）不对应七项事实，自定义键必须放行。

    2026-10-20 实测：具体需求下模型给出的「表单字段」「刷新方式」两问，
    因 key 不在事实缺口里被全丢——那正是最该问的范围/选型问题。
    """
    probe = _probe(
        *([0.9] * 7),
        questions=[AskQuestion(key="form_fields", question="表单要哪些字段?", header="字段")],
    )
    items = build_unknowns(probe, _clear_facts())
    assert [i.key for i in items] == ["form_fields"]
    assert items[0].reason == EXECUTION_REASON


def test_facts_and_custom_keys_coexist() -> None:
    """事实缺口与自定义键同轮出现时都保留，顺序按模型给的来。"""
    probe = _probe(
        *([0.9] * 7),
        questions=[_ask("form_fields"), _ask("test_file_exists")],
    )
    items = build_unknowns(probe, _facts())
    assert [i.key for i in items] == ["form_fields", "test_file_exists"]


def test_answered_key_skipped() -> None:
    probe = _probe(*([0.9] * 7), questions=[_ask("test_file_exists"), _ask("token_defined")])
    items = build_unknowns(
        probe,
        _facts(),
        clarifications={"test_file_exists": "写到 src/ui/__tests__"},
    )
    assert [i.key for i in items] == ["token_defined"]


def test_all_clear_yields_empty() -> None:
    """取证全过 + 模型未提问 → 零提问（时机仍由模型决定）。"""
    facts = [FactResult(k, True, "ok") for k in _ALL_KEYS]
    assert build_unknowns(_probe(*([0.9] * 7)), facts) == []


class TestLintQuestions:
    """形态合规检查：只报告不修改（用户 2026-10-20 裁定），且不含原文（MUST-19）。"""

    def test_compliant_question_has_no_issue(self) -> None:
        question = AskQuestion(
            key="ux",
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
            key="ux",
            question="导出入口放哪里",  # 缺问号
            header="这是一个超过十二字符的短标签",
            options=[AskOption(label="唯一的选项名称太长了", description="说明")],  # 只有 1 个
        )
        issues = lint_questions([question])
        assert "q0.question_no_mark" in issues
        assert "q0.header_too_long" in issues
        assert "q0.options_count" in issues
        assert "q0.label_too_long" in issues

    def test_reports_forbidden_punctuation(self) -> None:
        question = AskQuestion(
            key="ux",
            question="选哪个?",
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
            key="ux",
            question="含敏感路径 D:/secret 的问题",
            options=[AskOption(label="a", description="b")],
        )
        issues = lint_questions([question])
        assert all("secret" not in issue for issue in issues)
        assert all(issue.startswith("q0.") for issue in issues)


def test_guardrail_round_trigger() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    g = GuardrailState(rounds=10)
    assert g.should_trigger(cfg) is True
    assert GuardrailState(rounds=9).should_trigger(cfg) is False


def test_guardrail_cost_trigger_and_zero_disabled() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert GuardrailState(rounds=0, cost_tokens=5000).should_trigger(cfg) is False  # 预算 0=禁用
    rich = AppConfig(_env_file=None, followup_cost_budget=1000.0)  # type: ignore[call-arg]
    assert GuardrailState(rounds=0, cost_tokens=1000).should_trigger(rich) is True


def test_guardrail_reset() -> None:
    g = GuardrailState(rounds=10)
    g.reset()
    assert g.rounds == 0
