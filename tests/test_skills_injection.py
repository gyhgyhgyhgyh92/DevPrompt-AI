"""技能正文注入：命中才注入、停用不注入、预算截断。"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_service import _service


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DB_PATH", str(tmp_path / "main.db"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    service, _ = _service()
    return service


async def test_custom_skill_injected_only_when_matched(svc) -> None:  # type: ignore[no-untyped-def]
    await svc.update_settings(
        {
            "skills": [
                {"name": "接口规范", "description": "统一返回结构", "body": "所有接口返回 {code,data}"}
            ]
        }
    )
    block = await svc._skill_block("按接口规范新增一个查询接口")  # noqa: SLF001
    assert "接口规范" in block and "code,data" in block

    empty = await svc._skill_block("把按钮改成蓝色")  # noqa: SLF001
    assert empty == ""


async def test_disabled_skill_not_injected(svc) -> None:  # type: ignore[no-untyped-def]
    await svc.update_settings({"skills": [{"name": "停用规范", "body": "不该出现", "enabled": False}]})
    assert await svc._skill_block("停用规范怎么用") == ""  # noqa: SLF001


async def test_budget_truncates_body(svc, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(svc._cfg, "skills_max_chars", 10)  # noqa: SLF001
    await svc.update_settings({"skills": [{"name": "大技能", "body": "x" * 500}]})
    block = await svc._skill_block("大技能")  # noqa: SLF001
    assert block == ""  # 预算装不下 → 整条丢弃，不半截注入
