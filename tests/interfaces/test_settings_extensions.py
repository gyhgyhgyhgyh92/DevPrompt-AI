"""设置端点扩展段：Skill 自定义 CRUD 与 MCP 配置脱敏/整表替换/校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from test_service import _service


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "main.db"))
    service, _ = _service()
    return service


async def test_settings_exposes_empty_extension_sections(svc) -> None:  # type: ignore[no-untyped-def]
    view = await svc.get_settings()
    assert view["skills"] == {"dirs": [], "items": []}
    assert view["mcp_servers"] == []


async def test_custom_skill_create_replace_delete(svc) -> None:  # type: ignore[no-untyped-def]
    view = await svc.update_settings(
        {"skills": [{"name": "接口规范", "description": "统一返回", "body": "正文"}]}
    )
    items = view["skills"]["items"]
    assert [item["name"] for item in items] == ["接口规范"]
    assert items[0]["source"] == "custom"

    # 整表替换：换一条 → 旧条目被删除
    view = await svc.update_settings({"skills": [{"name": "新技能", "body": "b"}]})
    assert [item["name"] for item in view["skills"]["items"]] == ["新技能"]

    # None = 不动
    view = await svc.update_settings({"process": {"telemetry": True}})
    assert [item["name"] for item in view["skills"]["items"]] == ["新技能"]


async def test_mcp_server_masking_and_retention(svc) -> None:  # type: ignore[no-untyped-def]
    view = await svc.update_settings(
        {
            "mcp_servers": [
                {
                    "name": "本地工具",
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-m", "demo"],
                    "env": {"API_KEY": "plain-secret"},
                    "enabled": True,
                }
            ]
        }
    )
    server = view["mcp_servers"][0]
    assert server["env"]["API_KEY"] == "••••••"
    assert "plain-secret" not in str(view)
    sid = server["id"]

    # 同 id 回传掩码 → 沿用旧明文；改 enabled 生效
    view = await svc.update_settings(
        {
            "mcp_servers": [
                {
                    "id": sid,
                    "name": "本地工具",
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-m", "demo"],
                    "env": {"API_KEY": "••••••"},
                    "enabled": False,
                }
            ]
        }
    )
    assert view["mcp_servers"][0]["enabled"] is False
    from devprompt_ai.memory.settings_store import read_mcp_servers

    assert read_mcp_servers()[0]["env"]["API_KEY"] == "plain-secret"


async def test_mcp_rejects_shell_metacharacters(svc) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        await svc.update_settings(
            {"mcp_servers": [{"name": "危险", "command": "rm -rf / && echo done"}]}
        )
