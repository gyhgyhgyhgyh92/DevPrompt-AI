"""思考过程文案纯函数测试（MUST-19：文案不得泄露绝对路径与用户原句）。"""

from devprompt_ai.domain.progress import (
    candidates_text,
    clarification_text,
    display_path,
    facts_text,
    generation_text,
    manual_required_text,
    retrieval_text,
    symbols_text,
    target_text,
)


class TestDisplayPath:
    def test_windows_absolute_keeps_last_two_segments(self) -> None:
        assert display_path(r"D:\Works\repo\src\api.ts") == "src/api.ts"

    def test_unix_absolute_keeps_last_two_segments(self) -> None:
        assert display_path("/home/me/repo/src/api.ts") == "src/api.ts"

    def test_relative_path_untouched(self) -> None:
        assert display_path("src/api.ts") == "src/api.ts"

    def test_target_text_never_leaks_drive(self) -> None:
        text = target_text("handleSubmit", r"D:\Works\repo\src\api.ts", 42)

        assert "D:" not in text
        assert "handleSubmit" in text
        assert "src/api.ts:42" in text

    def test_target_text_without_line(self) -> None:
        assert "src/api.ts" in target_text("f", "src/api.ts", 0)
        assert ":0" not in target_text("f", "src/api.ts", 0)


class TestNodeTexts:
    def test_retrieval_and_symbols(self) -> None:
        assert retrieval_text()
        assert "1200" in symbols_text(1200)

    def test_candidates_two_branches(self) -> None:
        assert "压到 25 条" in candidates_text(80, 25)
        assert "全部进入候选" in candidates_text(12, 12)

    def test_manual_required_mentions_count(self) -> None:
        assert "2 个符号" in manual_required_text(2)

    def test_facts_counts(self) -> None:
        assert "7 项中 5 项通过" in facts_text(5, 7)

    def test_clarification_and_generation(self) -> None:
        assert "2 处" in clarification_text(2)
        assert generation_text() == "正在生成方案。"
