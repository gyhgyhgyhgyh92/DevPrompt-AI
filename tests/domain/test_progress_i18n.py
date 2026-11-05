"""进度流文案的双语直出（2026-11-06，F-209 后端双语）。

默认 zh-CN 的文案必须与既有测试里断言的逐字一致（既有 1000+ 测试兜底），
这里只钉住「同一函数在 en 下确实换成了英文」与档位名的双语渲染。
"""

from __future__ import annotations

from devprompt_ai.domain.progress import (
    candidates_text,
    facts_text,
    generation_text,
    level_label,
    level_text,
    recommendation_text,
    target_text,
)


def test_level_label_bilingual() -> None:
    assert level_label("A") == "A 保守"
    assert level_label("A", "en") == "A conservative"
    assert level_label("C", "en") == "C aggressive"
    # 未知档位原样返回，不猜
    assert level_label("Z", "en") == "Z"


def test_progress_lines_switch_language() -> None:
    zh = candidates_text(matched=30, kept=25)
    en = candidates_text(matched=30, kept=25, locale="en")
    assert "压到 25 条候选" in zh
    assert "kept 25 candidates" in en

    assert "事实核对完成" in facts_text(passed=5, total=7)
    assert "5 of 7 passed" in facts_text(passed=5, total=7, locale="en")

    assert "选中目标 echo" in target_text("echo", "src/a.py", 12)
    assert "Target selected: echo" in target_text("echo", "src/a.py", 12, locale="en")


def test_generation_text_uses_locale_separator() -> None:
    zh = generation_text(["A", "B"])
    en = generation_text(["A", "B"], "en")
    assert zh == "开始生成 2 套方案（A 保守、B 标准）。"
    assert en == "Generating 2 variants (A conservative, B standard)."


def test_level_text_unknown_confidence() -> None:
    assert "未评估" in level_text("B", None)
    assert "not assessed" in level_text("B", None, locale="en")
    assert "0.72" in level_text("C", 0.72, locale="en")


def test_recommendation_text_branches() -> None:
    marked = recommendation_text(True, "B", 0.12, "", locale="en")
    assert "recommending level B standard" in marked

    with_reason = recommendation_text(True, "C", 0.2, "上下文最完整", locale="en")
    assert "上下文最完整" in with_reason  # reason 由调用方给，本层不翻译

    unmarked = recommendation_text(False, "A", 0.05, "未达推荐阈值", locale="en")
    assert "best is level A conservative" in unmarked
