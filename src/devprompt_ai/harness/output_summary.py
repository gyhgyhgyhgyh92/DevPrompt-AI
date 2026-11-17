"""工具输出摘要（C1–C2、C5）：按语义密度设阈值，按成功/失败走两套策略。

核心纪律：截断必须**可见**，且 footer 明确告诉模型「不要重跑命令」——
这是 doom-loop 的根因修复（模型看不到完整输出就会重复执行同一命令）。
"""

from __future__ import annotations

import re
from typing import Final

#: 阈值系数：语义密度越低的工具越早截断。
THRESHOLD_FACTORS: Final[dict[str, float]] = {
    "read_file": 2.0,
    "read_section": 2.0,
    "run_tests": 1.5,
    "bash": 1.0,
    "grep": 0.67,
    "glob": 0.5,
    "repo_map": 0.5,
}
DEFAULT_MIN_CHARS: Final[int] = 4_000
_SUCCESS_LINES: Final[int] = 40
_FAILURE_HEAD: Final[int] = 10
_FAILURE_TAIL: Final[int] = 10
_FAILURE_ANCHOR_BUDGET: Final[int] = 60
_ERROR_RE: Final = re.compile(r"error|exception|traceback|failed|错误|失败", re.IGNORECASE)


def threshold_for(tool: str, *, min_chars: int = DEFAULT_MIN_CHARS) -> int:
    return int(min_chars * THRESHOLD_FACTORS.get(tool, 1.0))


def summarize_output(
    text: str,
    *,
    success: bool,
    success_lines: int = _SUCCESS_LINES,
    failure_budget: int = _FAILURE_ANCHOR_BUDGET,
) -> str:
    """成功只留尾部；失败保留头 + 错误锚段 + 尾，避免错过关键报错。"""
    lines = text.splitlines()
    if len(lines) <= success_lines:
        return text
    if success:
        return "\n".join(lines[-success_lines:])

    tail = lines[-_FAILURE_TAIL:]
    anchors: list[str] = lines[:_FAILURE_HEAD]
    for index, line in enumerate(lines):
        if _ERROR_RE.search(line):
            start = max(0, index - 2)
            anchors.extend(lines[start : index + 3])
            if len(anchors) >= failure_budget:
                break
    head = anchors[:failure_budget]
    return "\n".join([*head, "…（中间省略）…", *tail])


def with_footer(text: str, raw_path: str) -> str:
    """附上回读指针；路径为空时也给出「不要重跑」的提示。"""
    if not raw_path:
        return f"{text}\n…（输出已截断，不要重跑命令）"
    return f"{text}\nfull output: read_file {raw_path} — 不要重跑命令"
