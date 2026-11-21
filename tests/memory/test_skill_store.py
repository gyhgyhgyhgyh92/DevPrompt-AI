"""自定义技能 CRUD。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from devprompt_ai.memory.skill_store import SQLiteSkillStore


def _store(tmp_path: Path) -> SQLiteSkillStore:
    store = SQLiteSkillStore(str(tmp_path / "skills.db"))
    asyncio.run(store.init_schema())
    return store


def test_create_update_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)

    async def _go() -> None:
        created = await store.upsert(
            name="接口规范", description="统一返回结构", body="正文", domains=["code"]
        )
        assert created.meta.source == "custom"
        rows = await store.list_all()
        assert len(rows) == 1 and rows[0].meta.name == "接口规范"

        updated = await store.upsert(
            name="接口规范", description="改过", body="新正文", skill_id=created.meta.skill_id
        )
        assert updated.meta.skill_id == created.meta.skill_id
        rows = await store.list_all()
        assert rows[0].meta.description == "改过"

        assert await store.delete(created.meta.skill_id) is True
        assert await store.list_all() == []

    asyncio.run(_go())


def test_disabled_skill_kept_but_marked(tmp_path: Path) -> None:
    store = _store(tmp_path)

    async def _go() -> None:
        await store.upsert(name="停用项", enabled=False)
        rows = await store.list_all()
        assert rows[0].meta.enabled is False

    asyncio.run(_go())
