"""本轮目标锚点（2026-11-05）：把目标、范围、约束从对话历史里抽出来交给运行时持有。

天枢 TaskContract 的轻量移植（`src/context/task-contract.ts:11-35`）——只保留对抗
「摘要漂移」所需的四类内容，**去掉 status 与 plan 相关字段**：本项目不做计划确认门，
锚点纯内部状态，用户不可见、无额外交互。

价值：多轮上下文按预算裁剪，第 9 轮起历史只剩一句 80 字摘要；锚点作为可再生投影
注入 current 层（永不裁剪），保证「目标不随摘要漂移」。

纯数据 + 纯函数，零 I/O（MUST-06）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Final

#: 目标正文上限：避免长原句挤占 current 层
_OBJECTIVE_LIMIT: Final = 200
#: 渲染整块上限（本模块唯一的体积约束，注入后不参与历史裁剪）
_RENDER_LIMIT: Final = 300
#: 条数上限：锚点是「锚」，不是备忘录
_MAX_SCOPE: Final = 6
_MAX_CONSTRAINTS: Final = 4
_MAX_CRITERIA: Final = 4

#: 原句里显式提到的文件路径（POSIX / Windows 分隔符都认）
_PATH_RE: Final = re.compile(
    r"[A-Za-z0-9_\-./\\]+\.(?:tsx?|jsx?|vue|py|go|java|rs|css|scss|less|html)\b"
)
_SENTENCE_SPLIT: Final = re.compile(r"[。！？；\n]+")
#: 口语前缀：只在句首剥离一次，不碰句中的词
_GREETING_PREFIXES: Final = (
    "帮我",
    "帮忙",
    "请",
    "麻烦",
    "我想",
    "我要",
    "需要",
    "能不能",
    "可以",
    "希望",
)
#: 约束句判定词。刻意不用「别」「只」：单字在「区别」「只是」里会误命中。
_CONSTRAINT_WORDS: Final = (
    "不要",
    "不能",
    "不得",
    "不准",
    "禁止",
    "必须",
    "务必",
    "保持",
    "兼容",
    "勿",
    "never",
    "must",
    "should not",
    "don't",
)

#: 默认成功标准：对「产出提示词」这一交付物而言恒成立的两条
_DEFAULT_CRITERIA: Final = (
    "产出的提示词可直接复制给编码 Agent 执行",
    "正文中的路径与行号必须来自本次取证，不得编造",
)


@dataclass(frozen=True, slots=True)
class TurnAnchor:
    """一轮的目标锚点。字段全部为原始值，可直接 JSON 落库。"""

    objective: str
    scope_paths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = _DEFAULT_CRITERIA
    created_at_turn: int = 0
    updated_at_turn: int = 0


def _normalize_objective(sentence: str) -> str:
    """去口语前缀 + 取首段 + 截断。空结果逐级回退，保证锚点永不为空。"""
    original = sentence.strip()
    text = original
    for prefix in _GREETING_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].lstrip("，, ")
            break
    first = _SENTENCE_SPLIT.split(text)[0].strip()
    return (first or text or original)[:_OBJECTIVE_LIMIT]


def _extract_paths(sentence: str) -> tuple[str, ...]:
    """抽取原句显式提到的文件路径（去重保序，最多 _MAX_SCOPE 条）。"""
    seen: dict[str, None] = {}
    for raw in _PATH_RE.findall(sentence):
        path = raw.replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if path:
            seen.setdefault(path, None)
    return tuple(seen)[:_MAX_SCOPE]


def _extract_constraints(sentence: str) -> tuple[str, ...]:
    """按句拆分，保留命中约束词的句子（去重保序，单句截 80 字符）。"""
    seen: dict[str, None] = {}
    for segment in _SENTENCE_SPLIT.split(sentence):
        clause = segment.strip()
        if clause and any(word in clause for word in _CONSTRAINT_WORDS):
            seen.setdefault(clause[:80], None)
    return tuple(seen)[:_MAX_CONSTRAINTS]


def _merge_unique(base: tuple[str, ...], extra: tuple[str, ...], limit: int) -> tuple[str, ...]:
    """保持 base 顺序在前，追加 extra 中未出现过的项。"""
    merged: dict[str, None] = dict.fromkeys(base)
    for item in extra:
        merged.setdefault(item, None)
    return tuple(merged)[:limit]


def extract_anchor(sentence: str, turn_index: int) -> TurnAnchor:
    """从原句抽取锚点。本轮首次调用（或旧会话无锚点）时使用。"""
    return TurnAnchor(
        objective=_normalize_objective(sentence),
        scope_paths=_extract_paths(sentence),
        constraints=_extract_constraints(sentence),
        created_at_turn=turn_index,
        updated_at_turn=turn_index,
    )


def merge_followup(
    anchor: TurnAnchor, sentence: str, *, turn_index: int | None = None
) -> TurnAnchor:
    """把新一轮原句并入锚点：只追加范围与约束，**不重写 objective**。

    无新增内容时返回原对象（保 identity，供上层判「本轮无变化」）。
    """
    scope = _merge_unique(anchor.scope_paths, _extract_paths(sentence), _MAX_SCOPE)
    constraints = _merge_unique(
        anchor.constraints, _extract_constraints(sentence), _MAX_CONSTRAINTS
    )
    if scope == anchor.scope_paths and constraints == anchor.constraints:
        return anchor
    return replace(
        anchor,
        scope_paths=scope,
        constraints=constraints,
        updated_at_turn=anchor.updated_at_turn if turn_index is None else turn_index,
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_anchor(anchor: TurnAnchor) -> str:
    """渲染为稳定文本块。字段固定、顺序固定，同一锚点渲染结果字节相同。"""
    if not anchor.objective:
        return ""
    lines = [f"【本轮目标】{anchor.objective}"]
    if anchor.scope_paths:
        lines.append("【范围】" + "、".join(anchor.scope_paths))
    if anchor.constraints:
        lines.append("【约束】" + "；".join(anchor.constraints))
    if anchor.success_criteria:
        lines.append("【成功标准】" + "；".join(anchor.success_criteria))
    return _clip("\n".join(lines), _RENDER_LIMIT)


def _tuple_of_str(raw: object, limit: int) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str) and item)[:limit]


def _int_of(raw: object) -> int:
    return raw if isinstance(raw, int) and raw >= 0 else 0


def anchor_from_payload(payload: object) -> TurnAnchor | None:
    """从 `session.data["turn_anchor"]` 还原。

    缺字段、类型不符或 objective 为空一律返回 ``None``——调用方据此重新抽取，
    旧会话（改造前无此键）等价于「没有锚点」。
    """
    if not isinstance(payload, dict):
        return None
    objective = payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    return TurnAnchor(
        objective=objective[:_OBJECTIVE_LIMIT],
        scope_paths=_tuple_of_str(payload.get("scope_paths"), _MAX_SCOPE),
        constraints=_tuple_of_str(payload.get("constraints"), _MAX_CONSTRAINTS),
        success_criteria=_tuple_of_str(payload.get("success_criteria"), _MAX_CRITERIA)
        or _DEFAULT_CRITERIA,
        created_at_turn=_int_of(payload.get("created_at_turn")),
        updated_at_turn=_int_of(payload.get("updated_at_turn")),
    )


def anchor_to_payload(anchor: TurnAnchor) -> dict[str, Any]:
    """序列化为可入 `session.data` 的 JSON 友好结构（tuple → list）。"""
    return {
        "objective": anchor.objective,
        "scope_paths": list(anchor.scope_paths),
        "constraints": list(anchor.constraints),
        "success_criteria": list(anchor.success_criteria),
        "created_at_turn": anchor.created_at_turn,
        "updated_at_turn": anchor.updated_at_turn,
    }
