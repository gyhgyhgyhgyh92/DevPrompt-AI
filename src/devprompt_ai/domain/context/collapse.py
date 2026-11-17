"""语义折叠：按工具类型抽取「能支撑判断」的最小信息，而不是机械截断。

例：grep 不需要 200 行命中，只需要「14 处命中、8 个文件、路径样例」。
"""

from __future__ import annotations

import re
from typing import Final

from devprompt_ai.domain.context.micro import micro_compact

_ERROR_HINTS: Final[tuple[str, ...]] = (
    "error",
    "exception",
    "traceback",
    "failed",
    "失败",
    "错误",
)
_DEF_RE: Final = re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func)\s+(\w+)")
_MAX_SAMPLE_FILES: Final[int] = 5


def _artifact_ref(artifact_id: str) -> str:
    return f" [artifact:{artifact_id}]" if artifact_id else ""


def _collapse_grep(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    files: list[str] = []
    for line in lines:
        path = line.split(":", 1)[0]
        if path and path not in files:
            files.append(path)
    sample = "、".join(files[:_MAX_SAMPLE_FILES])
    return f"[collapsed grep: {len(lines)} matches in {len(files)} files: {sample}]"


def _collapse_read_file(text: str) -> str:
    lines = text.splitlines()
    names = [match.group(1) for line in lines if (match := _DEF_RE.match(line)) is not None][:5]
    suffix = f" · {', '.join(names)}" if names else ""
    return f"[collapsed read_file: {len(lines)} lines{suffix}]"


def _collapse_bash(text: str) -> str:
    lines = text.splitlines()
    errors = [line for line in lines if any(hint in line.lower() for hint in _ERROR_HINTS)][:3]
    tail = "\n".join(lines[-5:])
    body = f"[collapsed bash: {len(lines)} lines"
    if errors:
        body += " · errors: " + " | ".join(errors)
    return f"{body}]\n{tail}"


def _collapse_tests(text: str) -> str:
    lines = text.splitlines()
    failed = sum(1 for line in lines if line.strip().lower().startswith(("fail", "failed")))
    return f"[collapsed run_tests: {len(lines)} lines · failures={failed}]"


def collapse_tool_output(
    tool: str,
    text: str,
    *,
    artifact_id: str = "",
    fallback_chars: int = 1_200,
) -> str:
    """按工具名折叠；未知工具回落到 micro compaction（仍带可见标记）。"""
    if not text.strip():
        return text
    if tool == "grep":
        body = _collapse_grep(text)
    elif tool == "read_file":
        body = _collapse_read_file(text)
    elif tool == "bash":
        body = _collapse_bash(text)
    elif tool == "run_tests":
        body = _collapse_tests(text)
    else:
        return micro_compact(text, preview_chars=fallback_chars)
    return body + _artifact_ref(artifact_id)
