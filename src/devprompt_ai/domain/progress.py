"""思考过程文案（阶段进度）：纯函数零 I/O（MUST-06），由 service 在流程节点生成、
经 ProgressSink 推给前端逐字呈现。

约束（MUST-19）：文案**不得**出现用户原句与绝对路径。本模块的函数签名拿不到原句
（结构性保证），路径统一经 :func:`display_path` 收窄为仓库相对形式。

本地化（2026-11-06）：文案表在 ``common/i18n.py``；各函数末位可选 ``locale`` 参数，
默认 ``zh-CN``——旧调用零改动，服务层按会话语言传入即可。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr

#: 档位在语言包里的键（方案的差异是信息完整度，不是文风，MUST-28）。
_LEVEL_KEYS: Final[dict[str, str]] = {"A": "level.a", "B": "level.b", "C": "level.c"}


@dataclass(frozen=True, slots=True)
class ActionInfo:
    """一张动作卡片的展示载荷（真实执行过的工具调用，已脱敏）。

    detail 只允许出现仓库相对路径——绝对路径在观测层就被抹掉（MUST-19）。
    """

    title: str
    """动作名（按当前语言渲染，如「检索代码」「读取文件」）。"""

    detail: str
    """等宽预览：rg 参数（相对路径）或文件相对路径。"""

    scope: str = ""
    """范围标签，如「命中 4 行」「L1-146」；空串表示不展示。"""

    output: str = ""
    """脱敏并截断后的命令输出（≤20 行、≤2000 字符）；空串表示无输出可展示。"""

    status: Literal["ok", "failed"] = "ok"
    """动作结果：failed = 命令以非允许退出码结束（2026-11-04，对齐 CodeBuddy 的失败态可见）。"""

    duration_ms: int | None = None
    """动作真实耗时（毫秒，2026-11-07）。None = 未计时（旧数据或非观测来源），前端不展示耗时。"""


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """一条思考过程条目：文字段落（text）或动作卡片（action），二者取其一生效。"""

    text: str = ""
    action: ActionInfo | None = None
    #: 事件所属流程阶段（FlowState 值，如 RETRIEVING）；前端据此把过程挂到对应步骤下
    phase: str = ""


class ProgressSink(Protocol):
    """流程进度出口：由 HTTP 层以事件队列实现，service 只依赖此协议。"""

    async def emit(self, event: ProgressEvent) -> None: ...


def level_label(variant: str, locale: Locale = DEFAULT_LOCALE) -> str:
    """``A`` → ``A 保守``；未知档位原样返回（不猜）。"""
    key = _LEVEL_KEYS.get(variant)
    return f"{variant} {tr(key, locale)}" if key is not None else variant


def display_path(path: str) -> str:
    """路径展示口径：绝对路径只留末两段，避免泄露本机目录结构（MUST-19）。"""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    is_absolute = path.startswith(("/", "\\")) or (len(parts) > 0 and parts[0].endswith(":"))
    if is_absolute and len(parts) > 2:
        parts = parts[-2:]
    return "/".join(parts)


def retrieval_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.retrieval", locale)


def symbols_text(total: int, locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.symbols", locale, total=total)


def candidates_text(matched: int, kept: int, locale: Locale = DEFAULT_LOCALE) -> str:
    if matched > kept:
        return tr("progress.candidates_trimmed", locale, matched=matched, kept=kept)
    return tr("progress.candidates_all", locale, matched=matched)


def manual_required_text(matched: int, locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.manual_required", locale, matched=matched)


def target_text(name: str, path: str, line: int, locale: Locale = DEFAULT_LOCALE) -> str:
    location = f"{display_path(path)}:{line}" if line > 0 else display_path(path)
    return tr("progress.target", locale, name=name, location=location)


def facts_text(passed: int, total: int, locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.facts", locale, passed=passed, total=total)


def level_text(level: str, confidence: float | None, locale: Locale = DEFAULT_LOCALE) -> str:
    """研判结论提示。confidence 为 None 表示模型未给判断——不是「置信度 0」。"""
    shown = tr("progress.level_unknown", locale) if confidence is None else f"{confidence:.2f}"
    return tr("progress.level", locale, confidence=shown, level=level_label(level, locale))


def clarification_text(count: int, locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.clarification", locale, count=count)


def answering_text(locale: Locale = DEFAULT_LOCALE) -> str:
    """纯回答动作的进度文案（2026-11-05）。"""
    return tr("progress.answering", locale)


def generation_text(levels: Sequence[str], locale: Locale = DEFAULT_LOCALE) -> str:
    separator = tr("common.list_sep", locale)
    labels = separator.join(level_label(level, locale) for level in levels)
    return tr("progress.generation", locale, count=len(levels), labels=labels)


def single_variant_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.single_variant", locale)


def scoring_text(locale: Locale = DEFAULT_LOCALE) -> str:
    return tr("progress.scoring", locale)


def recommendation_text(
    marked: bool,
    variant: str,
    gap: float,
    reason: str,
    locale: Locale = DEFAULT_LOCALE,
) -> str:
    label = level_label(variant, locale)
    shown_gap = f"{gap:.2f}"
    if not marked:
        return tr(
            "progress.recommendation_unmarked",
            locale,
            reason=reason,
            label=label,
            gap=shown_gap,
        )
    if reason:
        return tr(
            "progress.recommendation_reasoned",
            locale,
            label=label,
            gap=shown_gap,
            reason=reason,
        )
    return tr("progress.recommendation_plain", locale, label=label, gap=shown_gap)
