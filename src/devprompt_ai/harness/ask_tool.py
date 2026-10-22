"""AskUserQuestion 工具定义与参数解析（2026-10-22，对齐 CodeBuddy SDK）。

官方契约（www.codebuddy.cn/docs/cli/sdk-permissions + sdk-typescript）::

    {"questions": [{"question": "...", "header": "≤12",
                    "options": [{"label": "...", "description": "..."}],
                    "multiSelect": false}]}          # 1~4 题，每题 2~4 个选项
    answers[question] = label                        # key = 问题原文

本模块只做两件事：给 ``Model.get_response(tools=...)`` 用的 schema，以及把
``tool_call.arguments`` 解析成 domain 的 ``AskQuestion`` 列表（结构校验 + 上限截断）。

**不做内容修正**：``label`` / ``description`` / ``header`` 原样保留——违规由
``domain.decision.followup.lint_questions`` 只告警不改写（用户 2026-10-20 裁定）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from devprompt_ai.domain.decision.followup import MAX_QUESTIONS
from devprompt_ai.domain.decision.port import AskOption, AskQuestion

ASK_TOOL_NAME: Final = "AskUserQuestion"

#: 合法的任务类型（与 domain 的 FactProbeOutput.task_kind 一致）
TaskKind = Literal["design", "execution"]

#: 单题选项上限（官方 2~4；多的问题截断，0 个的题目丢弃）。
MAX_OPTIONS: Final = 4

#: OpenAI function-tool 形态的参数 schema（字段与官方逐字对齐）。
ASK_TOOL_PARAMETERS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_QUESTIONS,
            "description": "要向用户确认的问题，按重要性排序",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "完整问句，以「?」结尾"},
                    "header": {"type": "string", "maxLength": 12, "description": "12 字内短标签"},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": MAX_OPTIONS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "选项名，1~5 个词（中文 ≤6 字）",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "选它的代价/后果",
                                },
                            },
                            "required": ["label", "description"],
                            "additionalProperties": False,
                        },
                    },
                    "multiSelect": {
                        "type": "boolean",
                        "description": "是否多选；取舍类必须 false",
                    },
                },
                "required": ["question", "header", "options", "multiSelect"],
                "additionalProperties": False,
            },
        },
        # 本项目扩展字段（非官方）：模型随工具调用声明任务类型，用于选提问原因文案。
        # 刻意不放进 required —— 官方四项仍是必需，缺省按 execution 处理。
        "taskKind": {
            "type": "string",
            "enum": ["design", "execution"],
            "description": (
                "本项目扩展：design=原句模糊需深挖 5 类；execution=范围已知只走 5 类闸门"
            ),
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

ASK_TOOL_DEFINITION: Final[dict[str, Any]] = {
    "type": "function",
    "function": {
        "name": ASK_TOOL_NAME,
        "description": (
            "信息不足时向用户提问，一次 1~4 个问题，每题 2~4 个选项。"
            "只问用户才知道的事（意图/范围/命名/是否补测试/验收口径）；"
            "不要问代码事实（文件位置、符号是否存在）；信息足够时不要调用。"
        ),
        "parameters": ASK_TOOL_PARAMETERS,
    },
}


def _options_of(raw: object) -> list[AskOption]:
    if not isinstance(raw, list):
        return []
    options: list[AskOption] = []
    for item in raw[:MAX_OPTIONS]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label == "":
            continue
        options.append(
            AskOption(label=label, description=str(item.get("description") or "").strip())
        )
    return options


def parse_ask_arguments(raw: str) -> list[AskQuestion] | None:
    """把 ``tool_call.arguments`` 解析成问题列表。

    返回 ``None`` 表示**没有可用的提问**（JSON 非法 / 缺 questions / 全部题目畸形），
    调用方据此走「不提问、直接生成」，并记 ``decision.ask_args_invalid``。

    ``key`` 留空：答案键是 ``question`` 原文，由 ``build_unknowns`` 决定，不在工具参数里。
    """
    try:
        payload = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return None

    parsed: list[AskQuestion] = []
    for item in raw_questions[:MAX_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if question == "":
            continue
        options = _options_of(item.get("options"))
        if not options:
            continue  # 没有可选项的题目无法作答，直接丢弃
        parsed.append(
            AskQuestion(
                key="",
                question=question,
                header=str(item.get("header") or "").strip(),
                options=options,
                multi_select=bool(item.get("multiSelect", False)),
            )
        )
    return parsed or None


@dataclass(frozen=True, slots=True)
class ParsedAsk:
    """工具调用解析结果：问题列表 + 任务类型（扩展字段，缺省 execution）。"""

    questions: list[AskQuestion]
    task_kind: TaskKind = "execution"


def parse_ask_call(raw: str) -> ParsedAsk | None:
    """解析 tool_call.arguments，同时取出扩展字段 ``taskKind``。

    返回 ``None`` 表示没有可用提问（与 :func:`parse_ask_arguments` 同口径）。
    """
    questions = parse_ask_arguments(raw)
    if questions is None:
        return None
    kind: TaskKind = "execution"
    try:
        payload = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("taskKind") == "design":
        kind = "design"
    return ParsedAsk(questions=questions, task_kind=kind)
