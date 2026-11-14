"""进度流文案的双语直出（2026-11-06，F-209 后端双语）。

默认 zh-CN 的文案必须与既有测试里断言的逐字一致（既有 1000+ 测试兜底），
这里只钉住「同一函数在 en 下确实换成了英文」与档位名的双语渲染。
"""

from __future__ import annotations

from devprompt_ai.domain.progress import (
    candidates_text,
    facts_text,
    generation_text,
    target_text,
)


def test_progress_lines_switch_language() -> None:
    zh = candidates_text(matched=30, kept=25)
    en = candidates_text(matched=30, kept=25, locale="en")
    assert "压到 25 条候选" in zh
    assert "kept 25 candidates" in en

    assert "事实核对完成" in facts_text(passed=5, total=7)
    assert "5 of 7 passed" in facts_text(passed=5, total=7, locale="en")

    assert "选中目标 echo" in target_text("echo", "src/a.py", 12)
    assert "Target selected: echo" in target_text("echo", "src/a.py", 12, locale="en")


def test_generation_text_switches_language() -> None:
    assert generation_text() == "正在生成方案。"
    assert generation_text("en") == "Generating the plan."
