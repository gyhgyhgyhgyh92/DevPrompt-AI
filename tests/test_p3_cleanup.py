"""P3 清理回归：token 口径统一、记忆归档、符号表/排序缓存有界 LRU。"""

from __future__ import annotations

import asyncio
from typing import Any

from devprompt_ai.domain.context.build_context import estimate_tokens as build_estimate
from devprompt_ai.domain.context.tokens import estimate_tokens as unified_estimate
from devprompt_ai.memory.project_note_store import ProjectNote, SQLiteProjectNoteStore


def test_token_estimate_unified() -> None:
    text = "把提交按钮改成 primary 颜色，中文 English mix"
    assert build_estimate(text) == unified_estimate(text)


def test_archive_stale_marks_old_notes(tmp_path: Any) -> None:
    store = SQLiteProjectNoteStore(str(tmp_path / "notes.db"))

    async def _run() -> None:
        note = ProjectNote(
            project_root="p", kind="target", key="old@x", value="v", evidence="",
            confidence=0.9, hit_count=0, last_hit_at=None, superseded_by="", source="test",
        )
        await store.upsert(note)
        count = await store.archive_stale("p", max_age_days=0)
        assert count >= 1
        hits = await store.search("p", target_key="old@x")
        assert all(item.key != "old@x" for item in hits)

    asyncio.run(_run())


def test_rank_cache_is_bounded() -> None:
    """排序缓存必须有容量上限：长进程内不能无限增长。"""
    from collections import OrderedDict

    from devprompt_ai import service as svc_module

    assert isinstance(svc_module._RANK_CACHE, OrderedDict)
    assert svc_module._RANK_CACHE_CAPACITY > 0


def test_symbol_table_multi_slot_lru() -> None:
    from devprompt_ai.harness.process import SymbolTableProvider

    class FakeRunner:
        calls = 0

        async def run(self, args: list[str], **_: Any) -> str:
            self.calls += 1
            return ""

    runner = FakeRunner()
    provider = SymbolTableProvider(runner, ttl_seconds=3600, capacity=2)  # type: ignore[arg-type]

    async def _run() -> None:
        provider.mtime_digest_override = "a"
        await provider.get("/proj/a")
        provider.mtime_digest_override = "b"
        await provider.get("/proj/b")
        calls_before = runner.calls
        provider.mtime_digest_override = "a"
        result = await provider.get("/proj/a")
        assert result.cache_hit is True
        assert runner.calls == calls_before  # 未重建
        # 刚访问过的 a 被移到最新，第三项目进入后驱逐的是 b（容量 2）
        provider.mtime_digest_override = "c"
        await provider.get("/proj/c")
        provider.mtime_digest_override = "b"
        evicted = await provider.get("/proj/b")
        assert evicted.cache_hit is False

    asyncio.run(_run())
