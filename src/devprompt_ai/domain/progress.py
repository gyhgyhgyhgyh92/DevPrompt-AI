"""思考过程文案（阶段进度）：纯函数零 I/O（MUST-06），由 service 在流程节点生成、
经 ProgressSink 推给前端逐字呈现。

约束（MUST-19）：文案**不得**出现用户原句与绝对路径。本模块的函数签名拿不到原句
（结构性保证），路径统一经 :func:`display_path` 收窄为仓库相对形式。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

#: 档位中文名（方案的差异是信息完整度，不是文风，MUST-28）。
LEVEL_NAMES: Final[dict[str, str]] = {"A": "保守", "B": "标准", "C": "激进"}


@dataclass(frozen=True, slots=True)
class ActionInfo:
    """一张动作卡片的展示载荷（真实执行过的工具调用，已脱敏）。

    detail 只允许出现仓库相对路径——绝对路径在观测层就被抹掉（MUST-19）。
    """

    title: str
    """动作中文名，如「检索代码」「读取文件」。"""

    detail: str
    """等宽预览：rg 参数（相对路径）或文件相对路径。"""

    scope: str = ""
    """范围标签，如「命中 4 行」「L1-146」；空串表示不展示。"""

    output: str = ""
    """脱敏并截断后的命令输出（≤20 行、≤2000 字符）；空串表示无输出可展示。"""

    status: Literal["ok", "failed"] = "ok"
    """动作结果：failed = 命令以非允许退出码结束（2026-11-04，对齐 CodeBuddy 的失败态可见）。"""


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


def level_label(variant: str) -> str:
    """``A`` → ``A 保守``；未知档位原样返回（不猜）。"""
    return f"{variant} {LEVEL_NAMES[variant]}" if variant in LEVEL_NAMES else variant


def display_path(path: str) -> str:
    """路径展示口径：绝对路径只留末两段，避免泄露本机目录结构（MUST-19）。"""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    is_absolute = path.startswith(("/", "\\")) or (len(parts) > 0 and parts[0].endswith(":"))
    if is_absolute and len(parts) > 2:
        parts = parts[-2:]
    return "/".join(parts)


def retrieval_text() -> str:
    return "开始分析这条提示词，先在你的项目里检索相关代码。"


def symbols_text(total: int) -> str:
    return f"符号表就绪，共 {total} 个符号参与匹配。"


def candidates_text(matched: int, kept: int) -> str:
    if matched > kept:
        return f"匹配到 {matched} 个相关符号，按相关度压到 {kept} 条候选（上限固定）。"
    return f"匹配到 {matched} 个相关符号，全部进入候选（未触及上限）。"


def manual_required_text(matched: int) -> str:
    return (
        f"只匹配到 {matched} 个符号，不足以自动定位目标，需要你补充具体符号名或文件路径后再继续。"
    )


def target_text(name: str, path: str, line: int) -> str:
    location = f"{display_path(path)}:{line}" if line > 0 else display_path(path)
    return f"选中目标 {name}（{location}），正在核对事实依据。"


def facts_text(passed: int, total: int) -> str:
    return f"事实核对完成：{total} 项中 {passed} 项通过。"


def level_text(level: str, confidence: float | None) -> str:
    """研判结论提示。confidence 为 None 表示模型未给判断——不是「置信度 0」。"""
    shown = "未评估" if confidence is None else f"{confidence:.2f}"
    return f"研判完成，整体置信度 {shown}，可输出 {level_label(level)} 档。"


def clarification_text(count: int) -> str:
    return f"研判出 {count} 处信息缺口，先和你确认再继续。"


def answering_text() -> str:
    """纯回答动作的进度文案（2026-11-05）。"""
    return "正在回答你的追问。"


def generation_text(levels: Sequence[str]) -> str:
    labels = "、".join(level_label(level) for level in levels)
    return f"开始生成 {len(levels)} 套方案（{labels}）。"


def single_variant_text() -> str:
    return "信息量只够输出 1 套保守方案，按规则跳过打分与推荐。"


def scoring_text() -> str:
    return "为各套方案打分，并结合你的历史偏好计算加权总分。"


def recommendation_text(marked: bool, variant: str, gap: float, reason: str) -> str:
    label = level_label(variant)
    if not marked:
        return f"综合评分完成，{reason}（最高为 {label} 档，领先 {gap:.2f}）。"
    if reason:
        return f"综合评分完成，推荐 {label} 档（领先 {gap:.2f}，{reason}）。"
    return f"综合评分完成，推荐 {label} 档（领先次优 {gap:.2f}）。"
