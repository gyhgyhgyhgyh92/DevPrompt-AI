"""AskUserQuestion 工具契约测试（2026-10-22，对齐 CodeBuddy SDK）。"""

from __future__ import annotations

import json

from devprompt_ai.harness.ask_tool import (
    ASK_TOOL_DEFINITION,
    ASK_TOOL_NAME,
    ASK_TOOL_PARAMETERS,
    MAX_OPTIONS,
    parse_ask_arguments,
    parse_ask_call,
)


def _question(index: int, *, options: int = 2, header: str = "范围") -> dict[str, object]:
    return {
        "question": f"第 {index} 个问题?",
        "header": header,
        "options": [
            {"label": f"选项{index}-{i}", "description": f"说明{i}"} for i in range(options)
        ],
        "multiSelect": False,
    }


class TestSchema:
    def test_tool_name_matches_official(self) -> None:
        assert ASK_TOOL_NAME == "AskUserQuestion"
        assert ASK_TOOL_DEFINITION["function"]["name"] == ASK_TOOL_NAME

    def test_question_count_bounds(self) -> None:
        questions = ASK_TOOL_PARAMETERS["properties"]["questions"]
        assert questions["minItems"] == 1
        assert questions["maxItems"] == 4

    def test_option_bounds_and_required_fields(self) -> None:
        item = ASK_TOOL_PARAMETERS["properties"]["questions"]["items"]
        options = item["properties"]["options"]
        assert options["minItems"] == 2
        assert options["maxItems"] == MAX_OPTIONS
        assert set(item["required"]) == {"question", "header", "options", "multiSelect"}
        assert set(options["items"]["required"]) == {"label", "description"}

    def test_header_limited_to_twelve(self) -> None:
        item = ASK_TOOL_PARAMETERS["properties"]["questions"]["items"]
        assert item["properties"]["header"]["maxLength"] == 12


class TestParse:
    def test_parses_official_shape(self) -> None:
        raw = json.dumps({"questions": [_question(1), _question(2, header="测试")]})

        parsed = parse_ask_arguments(raw)

        assert parsed is not None
        assert [q.question for q in parsed] == ["第 1 个问题?", "第 2 个问题?"]
        assert parsed[1].header == "测试"
        assert [o.label for o in parsed[0].options] == ["选项1-0", "选项1-1"]
        assert parsed[0].options[0].description == "说明0"
        assert parsed[0].multi_select is False

    def test_multi_select_passthrough(self) -> None:
        item = _question(1)
        item["multiSelect"] = True
        parsed = parse_ask_arguments(json.dumps({"questions": [item]}))
        assert parsed is not None and parsed[0].multi_select is True

    def test_key_is_left_empty_for_question_text(self) -> None:
        """答案键是 question 原文，工具参数里不带 key。"""
        parsed = parse_ask_arguments(json.dumps({"questions": [_question(1)]}))
        assert parsed is not None and parsed[0].key == ""

    def test_best_guess_passthrough(self) -> None:
        item = _question(1)
        item["bestGuess"] = "src/ui/button.tsx:12"

        parsed = parse_ask_arguments(json.dumps({"questions": [item]}))

        assert parsed is not None and parsed[0].best_guess == "src/ui/button.tsx:12"

    def test_missing_best_guess_is_empty(self) -> None:
        parsed = parse_ask_arguments(json.dumps({"questions": [_question(1)]}))
        assert parsed is not None and parsed[0].best_guess == ""

    def test_truncates_more_than_four_questions(self) -> None:
        raw = json.dumps({"questions": [_question(i) for i in range(6)]})
        parsed = parse_ask_arguments(raw)
        assert parsed is not None and len(parsed) == 4

    def test_truncates_more_than_max_options(self) -> None:
        raw = json.dumps({"questions": [_question(1, options=7)]})
        parsed = parse_ask_arguments(raw)
        assert parsed is not None and len(parsed[0].options) == MAX_OPTIONS

    def test_drops_question_without_options(self) -> None:
        bad = _question(1)
        bad["options"] = []
        raw = json.dumps({"questions": [bad, _question(2)]})

        parsed = parse_ask_arguments(raw)

        assert parsed is not None
        assert [q.question for q in parsed] == ["第 2 个问题?"]

    def test_all_questions_malformed_returns_none(self) -> None:
        bad = _question(1)
        bad["options"] = [{"label": "", "description": "无 label"}]
        assert parse_ask_arguments(json.dumps({"questions": [bad]})) is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_ask_arguments("{not json") is None
        assert parse_ask_arguments("") is None

    def test_missing_or_non_list_questions_returns_none(self) -> None:
        assert parse_ask_arguments(json.dumps({})) is None
        assert parse_ask_arguments(json.dumps({"questions": "nope"})) is None

    def test_does_not_rewrite_content(self) -> None:
        """不合规内容原样保留（header 超长不截断），由 lint 只告警。"""
        long_header = "这是一个远超十二字符的短标签"
        raw = json.dumps({"questions": [_question(1, header=long_header)]})

        parsed = parse_ask_arguments(raw)

        assert parsed is not None and parsed[0].header == long_header

    def test_skips_non_dict_items(self) -> None:
        raw = json.dumps({"questions": ["bad", _question(1), 3]})
        parsed = parse_ask_arguments(raw)
        assert parsed is not None and len(parsed) == 1


class TestTaskKindExtension:
    """本项目扩展字段 taskKind（非官方）：声明任务类型，缺省 execution。"""

    def test_schema_has_optional_task_kind(self) -> None:
        assert "taskKind" in ASK_TOOL_PARAMETERS["properties"]
        assert ASK_TOOL_PARAMETERS["properties"]["taskKind"]["enum"] == ["design", "execution"]
        # 官方四项仍是必需；扩展字段不强制
        assert ASK_TOOL_PARAMETERS["required"] == ["questions"]

    def test_parse_reads_design(self) -> None:
        raw = json.dumps({"taskKind": "design", "questions": [_question(1)]})
        parsed = parse_ask_call(raw)
        assert parsed is not None
        assert parsed.task_kind == "design"
        assert parsed.questions[0].question == "第 1 个问题?"

    def test_parse_defaults_to_execution(self) -> None:
        raw = json.dumps({"questions": [_question(1)]})
        parsed = parse_ask_call(raw)
        assert parsed is not None and parsed.task_kind == "execution"

    def test_unknown_kind_falls_back(self) -> None:
        raw = json.dumps({"taskKind": "weird", "questions": [_question(1)]})
        parsed = parse_ask_call(raw)
        assert parsed is not None and parsed.task_kind == "execution"

    def test_invalid_arguments_return_none(self) -> None:
        assert parse_ask_call("{bad") is None
