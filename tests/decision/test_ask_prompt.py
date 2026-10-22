"""提问 prompt 的条款钉死测试：规范（CodeBuddy-AskUserQuestion-提问规范.md）被误删会立刻红。

这些不是行为测试，而是「规范是否还在 prompt 里」的守门测试——
prompt 是目前唯一的约束载体（后端不做修正，用户 2026-10-20 裁定）。
"""

from __future__ import annotations

from devprompt_ai.decision.prompts import FACTS_SYSTEM, FACTS_USER


class TestTaskKind:
    def test_prompt_requests_task_kind(self) -> None:
        assert "task_kind" in FACTS_SYSTEM
        assert "task_kind" in FACTS_USER
        assert "design" in FACTS_SYSTEM and "execution" in FACTS_SYSTEM


class TestTwoTimings:
    def test_design_branch_covers_five_aspects(self) -> None:
        for keyword in ("技术方案", "用户体验", "边缘情况", "潜在风险", "权衡取舍"):
            assert keyword in FACTS_SYSTEM, keyword

    def test_execution_branch_lists_gates(self) -> None:
        for keyword in ("意图", "范围", "选型", "风险", "验收"):
            assert keyword in FACTS_SYSTEM, keyword


class TestWhenNotToAsk:
    def test_code_facts_are_forbidden(self) -> None:
        assert "代码事实" in FACTS_SYSTEM
        assert "在哪个文件" in FACTS_SYSTEM
        assert "不要推给用户" in FACTS_SYSTEM

    def test_generic_confirmation_is_forbidden(self) -> None:
        assert "还需要更多信息吗" in FACTS_SYSTEM
        assert "泛化确认" in FACTS_SYSTEM


class TestShapeConstraints:
    def test_question_must_end_with_mark(self) -> None:
        assert "以「?」结尾" in FACTS_SYSTEM

    def test_header_and_option_limits(self) -> None:
        assert "12 字符" in FACTS_SYSTEM
        assert "2~4 个" in FACTS_SYSTEM
        assert "1~5 个词" in FACTS_SYSTEM

    def test_multiselect_rule(self) -> None:
        assert "multiSelect" in FACTS_SYSTEM
        assert "必须 false" in FACTS_SYSTEM

    def test_forbidden_punctuation(self) -> None:
        assert "半角括号" in FACTS_SYSTEM
        assert "逗号+空格" in FACTS_SYSTEM

    def test_options_must_be_mutually_exclusive(self) -> None:
        assert "语义互斥" in FACTS_SYSTEM

    def test_model_must_not_fill_answers(self) -> None:
        assert "answers" in FACTS_SYSTEM
        assert "由界面回填" in FACTS_SYSTEM


class TestOutputContract:
    def test_user_prompt_routes_questions_through_tool(self) -> None:
        """JSON 里不再要求 questions：提问必须走工具调用（2026-10-22）。"""
        assert '"task_kind"' in FACTS_USER
        assert "AskUserQuestion" in FACTS_USER
        assert "不要输出任何 JSON" in FACTS_USER
        assert "不含 questions 字段" in FACTS_USER
