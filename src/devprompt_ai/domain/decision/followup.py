"""F-204 v1.1 自适应反问编排：unknowns 构建 + 软护栏状态（纯逻辑零 I/O，MUST-06）。"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from devprompt_ai.domain.decision.port import AskQuestion, FactProbeOutput
from devprompt_ai.domain.models import FactResult

_EVIDENCE_LIMIT = 120

#: 一次反问的问题上限（对齐 CodeBuddy SDK `AskUserQuestion` 的 1~4 个）。
#: 这是唯一保留的硬处理：整题截断。其余形态违规（header 超长、选项数越界）原样下发。
MAX_QUESTIONS = 4

#: 设计类（原句模糊）问题的缺失原因文案——这类问题不绑定取证失败项。
DESIGN_REASON = "需求较模糊，需要确认后再生成"

#: 执行类闸门问题（范围/选型/验收）的缺失原因——同样可能不绑定取证失败项。
EXECUTION_REASON = "需求存在需要确认的决策点"

_HEADER_LIMIT = 12
_LABEL_MAX_CJK = 6
_LABEL_MAX_WORDS = 5
_OPTION_RANGE = (2, 4)


def _normalize_question(text: str) -> str:
    """问题归一（2026-11-03）：抹平空白/标点/全半角差异，只留字母数字与汉字。

    模型改一个标点或换个空格就算「新问题」是重复追问的主因，故比对走归一化；
    答案键仍是问题原文（契约不变）。
    """
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def answered_headers(
    clarifications: Mapping[str, str], unknowns: Sequence[Mapping[str, Any]]
) -> set[str]:
    """已答题目对应的 header 集合（2026-11-03）。

    ``unknowns`` 是上一轮落进 session.data 的未知项（含 header/ask）；其中 ``ask``
    已在 ``clarifications`` 里的那些，其 header 视为「这件事已经问过了」。
    """
    answered = {_normalize_question(key) for key in clarifications}
    headers: set[str] = set()
    for item in unknowns:
        ask = str(item.get("ask", ""))
        header = str(item.get("header", "")).strip()
        if header != "" and _normalize_question(ask) in answered:
            headers.add(header)
    return headers


def _is_long_label(label: str) -> bool:
    text = label.strip()
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk > _LABEL_MAX_CJK or len(text.split()) > _LABEL_MAX_WORDS


def lint_questions(questions: Sequence[AskQuestion]) -> list[str]:
    """检查问题形态是否符合规范，**只报告不修改**（2026-10-20 用户裁定：原样展示）。

    返回形如 ``q0.header_too_long`` 的码：只含下标与规则名，不含模型原文（MUST-19）。
    ``service`` 把它发成 ``followup.question_lint`` 事件；前端不受影响。
    """
    issues: list[str] = []
    for index, question in enumerate(questions):
        prefix = f"q{index}"
        if not question.question.strip().endswith(("?", "？")):
            issues.append(f"{prefix}.question_no_mark")
        if len(question.header.strip()) > _HEADER_LIMIT:
            issues.append(f"{prefix}.header_too_long")
        if not _OPTION_RANGE[0] <= len(question.options) <= _OPTION_RANGE[1]:
            issues.append(f"{prefix}.options_count")
        if any(_is_long_label(option.label) for option in question.options):
            issues.append(f"{prefix}.label_too_long")
        texts = [
            question.header,
            *(option.label for option in question.options),
            *(option.description for option in question.options),
        ]
        if any("(" in text or ")" in text for text in texts):
            issues.append(f"{prefix}.halfwidth_paren")
        if any(", " in text for text in texts):
            issues.append(f"{prefix}.comma_space")
    return issues


#: 「不把代码事实推给用户」这条规则**只放在 prompt 里**，不做 key 白名单。
#:
#: 实测（2026-10-20，DeepSeek 3 次采样）：模型会把「按钮点击后什么行为」这类**合法意图
#: 问题**挂在 `symbol_in_file` 这个代码事实 key 上——按 key 过滤会 100% 误杀合法提问。
#: 内容正确性交给 prompt 的提问纪律（明确禁止问「在哪个文件/是否存在」）。
_ASK_DISCIPLINE_NOTE = "代码事实不推给用户：见 decision/prompts.py 的提问纪律"


class GuardrailConfig(Protocol):
    """护栏阈值契约（结构类型）：AppConfig 天然满足。

    domain 不 import devprompt_ai.config（check_architecture MUST-06 门禁），只声明所需能力。
    """

    @property
    def followup_soft_round_guard(self) -> int: ...

    @property
    def followup_cost_budget(self) -> float: ...


@dataclass(frozen=True, slots=True)
class UnknownOption:
    """反问选项（对齐官方 AskUserQuestion 的 options[]：label + description）。"""

    label: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class UnknownItem:
    """具体未决事实（MUST-26）：每问绑定一项；问法与选项由决策层给出。"""

    key: str
    reason: str
    best_guess: str
    ask: str
    header: str = ""
    options: tuple[UnknownOption, ...] = ()
    multi_select: bool = False


def build_unknowns(
    probe: FactProbeOutput,
    facts: Sequence[FactResult],
    *,
    clarifications: dict[str, str] | None = None,
    answered_header_set: Collection[str] | None = None,
) -> list[UnknownItem]:
    """把工具调用解析出的问题转成未知项（2026-10-22 起答案键 = ``question`` 原文）。

    对齐 CodeBuddy SDK：``answers[question] = label``，因此答案键也按问题原文。

    - ``questions`` 为空 → 本轮不提问（模型没调工具，或参数畸形已在上层记录）
    - 已答过的 question（**归一化后**比对）直接跳过；重复文本只保留第一次出现
    - ``answered_header_set`` 里的 header 整体跳过：模型改写措辞时靠这一层兜住，
      同一件事不会被追问第二次（2026-11-03；值由 :func:`answered_headers` 算出）
    - 截断到 :data:`MAX_QUESTIONS` 个；``facts`` 仅保留参数位（工具调用路径不再按事实键匹配）

    shortcut: header 级去重按「短标签相同即视为同一件事」，同标签下的**新**问题也会被
    跳过；此时退化为保守假设 + 未确认项（规范 §5 的兜底分支），需要精确区分时由模型换 header。
    """
    clar = {_normalize_question(key) for key in (clarifications or {})}
    answered = {_normalize_question(header) for header in (answered_header_set or ())}
    if not probe.questions:
        return []

    default_reason = DESIGN_REASON if probe.task_kind == "design" else EXECUTION_REASON
    asked: list[UnknownItem] = []
    seen: set[str] = set()
    for question in probe.questions:
        key = question.question.strip()
        header = question.header.strip()
        normalized = _normalize_question(key)
        if (
            key == ""
            or normalized == ""
            or normalized in clar
            or normalized in seen
            or (header != "" and _normalize_question(header) in answered)
        ):
            continue
        seen.add(normalized)
        best_guess = question.best_guess.strip()
        if not best_guess:
            # MUST-26：每问必须给当前最佳推断。模型没给时回退到取证证据，但必须过滤
            # 「未找到」——那是 `_ev()` 的字面占位，把它当推断展示等于告诉用户
            # 「最佳推断是：没找到」，比留空更误导（2026-11-05 真实冒烟发现）。
            ordered = [f.evidence for f in facts if not f.passed] + [
                f.evidence for f in facts if f.passed
            ]
            best_guess = next((e for e in ordered if e and e.strip() != "未找到"), "")
        asked.append(
            UnknownItem(
                key=key,
                reason=default_reason,
                best_guess=best_guess,
                ask=key,
                header=header,
                options=tuple(
                    UnknownOption(label=item.label.strip(), description=item.description.strip())
                    for item in question.options
                    if item.label.strip()
                ),
                multi_select=question.multi_select,
            )
        )
        if len(asked) >= MAX_QUESTIONS:
            break
    return asked


@dataclass(slots=True)
class GuardrailState:
    """MUST-26 软护栏：触发时不静默终止，由 service 转为显式用户裁决。"""

    rounds: int = 0
    cost_tokens: int = 0

    def should_trigger(self, cfg: GuardrailConfig) -> bool:
        if self.rounds >= cfg.followup_soft_round_guard:
            return True
        return cfg.followup_cost_budget > 0 and self.cost_tokens >= cfg.followup_cost_budget

    def reset(self) -> None:
        """用户裁决「继续追问」后清零。"""
        self.rounds = 0
        self.cost_tokens = 0
