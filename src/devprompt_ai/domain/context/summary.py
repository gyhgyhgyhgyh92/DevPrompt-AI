"""摘要后检与确定性兜底（纯函数）。

摘要模型可能漏掉关键状态；漏了不能硬用，也不能卡死流程——
改为生成一份**零 LLM 成本**的 9 段 handoff，保证「最坏情况仍然可继续」。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

#: 9 段结构：顺序固定，便于人读与机器比对。
HANDOFF_SECTIONS: Final[tuple[str, ...]] = (
    "用户核心需求",
    "技术决策",
    "涉及文件",
    "错误与诊断",
    "当前进度",
    "已完成",
    "待办",
    "最近工具轨迹",
    "下一步",
)


def _bullets(items: Sequence[str]) -> str:
    if not items:
        return "（无）"
    return "\n".join(f"- {item}" for item in items)


def deterministic_handoff(
    *,
    objective: str,
    decisions: Sequence[str] = (),
    files: Sequence[str] = (),
    errors: Sequence[str] = (),
    current: str = "",
    done: Sequence[str] = (),
    todo: Sequence[str] = (),
    recent_tools: Sequence[str] = (),
    next_step: str = "",
) -> str:
    """按固定 9 段生成可直接注入的 handoff 文本。"""
    blocks = [
        f"## {HANDOFF_SECTIONS[0]}\n{objective or '（未记录）'}",
        f"## {HANDOFF_SECTIONS[1]}\n{_bullets(decisions)}",
        f"## {HANDOFF_SECTIONS[2]}\n{_bullets(files)}",
        f"## {HANDOFF_SECTIONS[3]}\n{_bullets(errors)}",
        f"## {HANDOFF_SECTIONS[4]}\n{current or '（未记录）'}",
        f"## {HANDOFF_SECTIONS[5]}\n{_bullets(done)}",
        f"## {HANDOFF_SECTIONS[6]}\n{_bullets(todo)}",
        f"## {HANDOFF_SECTIONS[7]}\n{_bullets(recent_tools)}",
        f"## {HANDOFF_SECTIONS[8]}\n{next_step or '（未记录）'}",
    ]
    return "\n\n".join(blocks)


def summary_covers_state(summary: str, required: Sequence[str]) -> bool:
    """摘要必须覆盖全部关键项才算合格；空要求视为通过。"""
    return all(term in summary for term in required if term)


SUMMARY_SYSTEM: Final[str] = (
    "你是上下文压缩摘要器。把对话历史压缩成可继续工作的摘要，只输出摘要正文。\n"
    "必须完整保留：用户意图链（逐条、不合并）、已执行的写操作（不可省略）、"
    "当前进度与下一步。\n"
    "必须丢弃：冗长的工具原始输出、重复的探索过程、已被取代的结论。"
)


def build_summary_prompt(history: str, *, previous: str = "") -> tuple[str, str]:
    """构造摘要请求；已有摘要时要求无损迭代合并。"""
    merge = f"\n\n【已有摘要（请无损合并，不要丢信息）】\n{previous}" if previous.strip() else ""
    return SUMMARY_SYSTEM, f"待压缩的历史：\n{history}{merge}"


def choose_summary(
    llm_summary: str | None,
    *,
    required: Sequence[str],
    fallback: str,
) -> tuple[str, bool]:
    """摘要后检：不合格或缺失即回退确定性 handoff。

    返回 ``(最终摘要, 是否用了兜底)``；兜底是常规路径，不是异常。
    """
    if llm_summary is None or not llm_summary.strip():
        return fallback, True
    if not summary_covers_state(llm_summary, required):
        return fallback, True
    return llm_summary, False
