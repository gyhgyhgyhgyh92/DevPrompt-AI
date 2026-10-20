"""F-204 v1.1 自适应反问编排：unknowns 构建 + 软护栏状态（纯逻辑零 I/O，MUST-06）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from devprompt_ai.domain.decision.port import AskQuestion, FactProbeOutput
from devprompt_ai.domain.decision.probes import PROBE_ASK_TEXT
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
) -> list[UnknownItem]:
    """由决策层决定「问不问、怎么问」（对齐 CodeBuddy SDK 的 AskUserQuestion）。

    - ``questions`` 为空 → 模型判定信息已够，本轮不提问（档位仍受 resolve_level 约束，
      不会越级输出）
    - ``questions`` 非空 → 只接受绑定真实缺口的 key（防幻觉），按模型给的顺序截断到
      :data:`MAX_QUESTIONS` 个；没被问到的缺口留到下一轮
    - 模型给的问题全部对不上缺口 → 按缺口兜底生成，绝不静默丢弃（MUST-26）
    """
    clar = clarifications or {}
    judgment_by_key = {j.key: j for j in probe.judgments}
    gaps: dict[str, UnknownItem] = {}
    for fact in facts:
        if fact.key in clar:
            continue  # 已澄清（MUST-26：答复即解除该未知项）
        judgment = judgment_by_key.get(fact.key)
        if fact.passed and (judgment is None or judgment.passed):
            continue
        reason = (
            fact.evidence
            if not fact.passed
            else (f"研判置信度不足（{judgment.confidence:.2f}）" if judgment else "未判定")
        )
        gaps[fact.key] = UnknownItem(
            key=fact.key,
            reason=reason[:_EVIDENCE_LIMIT],
            best_guess=fact.evidence[:_EVIDENCE_LIMIT] if fact.passed else "",
            ask=PROBE_ASK_TEXT.get(fact.key, fact.key),
        )

    if not probe.questions:
        return []

    # 模型用自定义键（不绑定取证失败项）时也允许提问：设计类深挖与执行类闸门
    # （范围/选型/验收）本来就不对应七项事实；只认事实键会让这些合理问题被静默丢弃
    # （2026-10-20 实测：具体需求下模型的 2 个闸门问题全被丢）。
    default_reason = DESIGN_REASON if probe.task_kind == "design" else EXECUTION_REASON
    for index, question in enumerate(probe.questions):
        key = question.key.strip() or f"q-{index}"
        if key in clar:
            continue  # 同一键答过就不再问（模型换个键复述由 10 轮软护栏兜底）
        gaps.setdefault(
            key,
            UnknownItem(
                key=key, reason=default_reason, best_guess="", ask=question.question.strip()
            ),
        )

    asked: list[UnknownItem] = []
    seen: set[str] = set()
    for index, question in enumerate(probe.questions):
        # design 允许模型用自定义键（空键归一为 q-{i}，避免去重失效）
        key = question.key.strip() or f"q-{index}"
        gap = gaps.get(key)
        if gap is None or key in seen:
            continue
        seen.add(key)
        # 不合规产出原样下发（用户 2026-10-20 裁定）：此处不做 label/description/header 截断，
        # 违规只由 lint_questions 记日志，避免「悄悄修正」掩盖真实问题
        options = tuple(
            UnknownOption(label=item.label.strip(), description=item.description.strip())
            for item in question.options
            if item.label.strip()
        )
        asked.append(
            replace(
                gap,
                ask=question.question.strip() or gap.ask,
                header=question.header.strip(),
                options=options,
                multi_select=question.multi_select,
            )
        )
        if len(asked) >= MAX_QUESTIONS:
            break
    return asked or list(gaps.values())[:MAX_QUESTIONS]


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
