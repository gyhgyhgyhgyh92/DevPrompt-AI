"""L2 项目记忆（2026-10-20）：检索排序、衰减、命中回写、superseded、自动写入分级。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devprompt_ai.domain.models import ProjectNote
from devprompt_ai.memory.project_note_store import (
    SQLiteProjectNoteStore,
    normalize_key,
    score_note,
)

_ROOT = "D:/repo"


def _store(tmp_path: Path) -> SQLiteProjectNoteStore:
    return SQLiteProjectNoteStore(str(tmp_path / "notes.db"))


def _note(key: str, *, kind: str = "decision", confidence: float = 0.8, **kw: Any) -> ProjectNote:
    return ProjectNote(
        project_root=_ROOT,
        kind=kind,
        key=key,
        value=str(kw.get("value", f"value for {key}")),
        confidence=confidence,
        superseded_by=str(kw.get("superseded_by", "")),
        source=str(kw.get("source", "auto")),
    )


class TestNormalizeKey:
    def test_keeps_symbol_and_tail_two_segments(self) -> None:
        assert normalize_key("SubmitButton", "src/ui/Button.tsx") == "submitbutton@ui/button.tsx"

    def test_windows_separators_and_case(self) -> None:
        assert normalize_key("SubmitButton", r"src\ui\Button.tsx") == "submitbutton@ui/button.tsx"


class TestScoring:
    def test_exact_key_beats_partial(self) -> None:
        exact = score_note(
            _note("submitbutton@ui/button.tsx"), target_key="submitbutton@ui/button.tsx", age_days=0
        )
        partial = score_note(
            _note("submitbutton@other/x.tsx"), target_key="submitbutton@ui/button.tsx", age_days=0
        )
        assert exact > partial > 0

    def test_unrelated_key_scores_zero(self) -> None:
        assert (
            score_note(_note("other@x/y.tsx"), target_key="submitbutton@ui/button.tsx", age_days=0)
            == 0
        )

    def test_decay_halves_at_half_life(self) -> None:
        fresh = score_note(_note("k@a/b.tsx"), target_key="k@a/b.tsx", age_days=0)
        old = score_note(_note("k@a/b.tsx"), target_key="k@a/b.tsx", age_days=90)
        assert old < fresh
        assert abs(old - fresh / 2) < 1e-6


class TestStore:
    async def test_search_orders_by_score_and_limits(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        for index in range(7):
            await store.upsert(
                _note(f"submitbutton@ui/button.tsx#{index}", confidence=0.9 - index * 0.1)
            )

        found = await store.search(_ROOT, target_key="submitbutton@ui/button.tsx", limit=5)

        assert len(found) == 5
        assert found[0].confidence >= found[-1].confidence

    async def test_search_writes_hit_counters(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        await store.upsert(_note("submitbutton@ui/button.tsx"))

        await store.search(_ROOT, target_key="submitbutton@ui/button.tsx")
        found = await store.search(_ROOT, target_key="submitbutton@ui/button.tsx")

        assert found[0].hit_count == 1  # 第一次命中已回写
        assert found[0].last_hit_at != ""

    async def test_superseded_notes_are_ignored(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        await store.upsert(_note("old@ui/button.tsx", superseded_by="new"))
        await store.upsert(_note("new@ui/button.tsx"))

        found = await store.search(_ROOT, target_key="new@ui/button.tsx")

        assert [note.key for note in found] == ["new@ui/button.tsx"]

    async def test_upsert_overwrites_same_key(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        await store.upsert(_note("k@a/b.tsx", value="旧值"))
        await store.upsert(_note("k@a/b.tsx", value="新值"))

        found = await store.search(_ROOT, target_key="k@a/b.tsx")

        assert found[0].value == "新值"

    async def test_record_from_session_writes_target_decision_rejected(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        data: dict[str, Any] = {
            "target": {"name": "SubmitButton", "path": "src/ui/Button.tsx", "line": 12},
            "variants": [
                {"level": "A", "title": "只改配色"},
                {"level": "B", "title": "改配色并补状态"},
            ],
            "ranking": {"variant": "B"},
        }

        await store.record_from_session(_ROOT, data)
        found = await store.search(_ROOT, target_key="submitbutton@ui/button.tsx", limit=10)

        kinds = {note.kind for note in found}
        assert kinds == {"target", "decision", "rejected_option"}
        assert any("选定 B" in note.value for note in found)
        assert any("未选 A" in note.value for note in found)

    async def test_record_from_v3_single_variant_writes_target_and_decision(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        data: dict[str, Any] = {
            "target": {"name": "SubmitButton", "path": "src/ui/Button.tsx", "line": 12},
            "variant": {"title": "改配色并补状态"},
        }

        await store.record_from_session(_ROOT, data)
        found = await store.search(_ROOT, target_key="submitbutton@ui/button.tsx", limit=10)

        kinds = {note.kind for note in found}
        assert kinds == {"target", "decision"}, "单套输出不写 rejected_option"
        assert any("改配色并补状态" in note.value for note in found)

    async def test_record_without_target_writes_nothing(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        await store.record_from_session(_ROOT, {"variants": [{"level": "A", "title": "x"}]})

        assert await store.search(_ROOT, target_key="", limit=10) == []
