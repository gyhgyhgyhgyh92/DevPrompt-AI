"""注册表读时归一化测试（M-912）。

锁定的核心行为：**六字段旧条目零迁移脚本可用，且在下次保存时自动升级**。
另锁定三条降级边界——数据文件由用户手工编辑，读取侧任何异常都必须静默兜底，
不能让配置丢失或让服务起不来。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from devprompt_ai.memory.settings_store import read_model_registry, write_model_registry

#: 迁移前的真实形态（六字段，无 capabilities / param_overrides）
_OLD_ENTRY: dict[str, Any] = {
    "id": "m-e94707cd",
    "label": "DeepSeek Flash",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-old-value",
    "model_id": "deepseek-flash",
}


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 settings.json 到临时目录（MUST-19：测试不得碰真实密钥文件）。"""
    path = tmp_path / "settings.json"
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(path))
    return path


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class TestReadTimeNormalisation:
    def test_six_field_entry_is_upgraded_on_read(self, settings_file: Path) -> None:
        _write(settings_file, {"models": [dict(_OLD_ENTRY)], "active_model_id": "m-e94707cd"})
        entry = read_model_registry()["models"][0]
        assert entry["capabilities"]["supports_tools"] is True
        assert entry["capabilities"]["max_context_length"] == 1_048_576

    def test_api_key_and_id_survive_normalisation(self, settings_file: Path) -> None:
        """归一化绝不能删掉密钥或条目 id——这是本模块最不能出错的地方。"""
        _write(settings_file, {"models": [dict(_OLD_ENTRY)]})
        entry = read_model_registry()["models"][0]
        assert entry["api_key"] == "sk-old-value"
        assert entry["id"] == "m-e94707cd"
        assert entry["base_url"] == _OLD_ENTRY["base_url"]

    def test_active_id_resolved(self, settings_file: Path) -> None:
        _write(settings_file, {"models": [dict(_OLD_ENTRY)], "active_model_id": "m-e94707cd"})
        assert read_model_registry()["active_model_id"] == "m-e94707cd"


class TestDegradation:
    def test_missing_file_yields_empty(self, settings_file: Path) -> None:
        assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}

    def test_corrupted_file_yields_empty(self, settings_file: Path) -> None:
        settings_file.write_text("{ 这不是合法 JSON", encoding="utf-8")
        assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}

    def test_wrong_types_yield_empty(self, settings_file: Path) -> None:
        _write(settings_file, {"models": "不是列表", "active_model_id": 123})
        assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}

    def test_dangling_active_id_is_cleared(self, settings_file: Path) -> None:
        """激活位指向已删除条目时回落为空，避免上层拿到悬空引用。"""
        _write(settings_file, {"models": [dict(_OLD_ENTRY)], "active_model_id": "已删除"})
        assert read_model_registry()["active_model_id"] == ""

    def test_disabled_store_yields_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
        assert read_model_registry() == {"providers": [], "models": [], "active_model_id": ""}


class TestWriteTimeUpgrade:
    def test_write_persists_full_structure(self, settings_file: Path) -> None:
        """读时补 + 写时全：保存后落盘必须是完整结构。"""
        write_model_registry([dict(_OLD_ENTRY)], "m-e94707cd")
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "capabilities" in saved["models"][0]

    def test_old_file_upgrades_after_save(self, settings_file: Path) -> None:
        _write(settings_file, {"models": [dict(_OLD_ENTRY)], "active_model_id": "m-e94707cd"})
        registry = read_model_registry()
        write_model_registry(registry["models"], registry["active_model_id"])
        reread = read_model_registry()["models"][0]
        assert reread["capabilities"]["max_context_length"] == 1_048_576

    def test_write_preserves_unknown_fields(self, settings_file: Path) -> None:
        write_model_registry([{**_OLD_ENTRY, "我的备注": "保留"}], None)
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved["models"][0]["我的备注"] == "保留"

    def test_write_drops_non_dict_items(self, settings_file: Path) -> None:
        """脏数据不该让整个写入失败——丢弃该条，其余照写。"""
        write_model_registry([dict(_OLD_ENTRY), "垃圾", None], None)  # type: ignore[list-item]
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert len(saved["models"]) == 1

    @pytest.mark.skipif(
        os.name != "posix", reason="Windows 的 chmod 只控制只读标志，POSIX 权限位语义不适用"
    )
    def test_write_keeps_0600_permissions(self, settings_file: Path) -> None:
        """MUST-19：密钥落盘处必须保持 0600（仅 POSIX 可断言权限位）。"""
        write_model_registry([dict(_OLD_ENTRY)], None)
        assert settings_file.stat().st_mode & 0o777 == 0o600

    def test_write_succeeds_with_secret_material(self, settings_file: Path) -> None:
        """全平台可断言的部分：含密钥的条目确实落盘了（权限语义由平台各自保证）。

        2026-10-18 起密钥只存供应商段一份，故断言移到 ``providers``。
        """
        write_model_registry([dict(_OLD_ENTRY)], None)
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved["providers"][0]["api_key"] == "sk-old-value"
        assert "api_key" not in saved["models"][0]

    def test_active_none_preserves_existing(self, settings_file: Path) -> None:
        _write(settings_file, {"models": [dict(_OLD_ENTRY)], "active_model_id": "m-e94707cd"})
        write_model_registry(read_model_registry()["models"], None)
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved["active_model_id"] == "m-e94707cd"


class TestRoundTrip:
    def test_read_write_read_is_stable(self, settings_file: Path) -> None:
        """归一化必须幂等——否则每次开关服务都会「进化」一次数据。"""
        write_model_registry([dict(_OLD_ENTRY)], "m-e94707cd")
        first = read_model_registry()
        write_model_registry(first["models"], first["active_model_id"])
        assert read_model_registry() == first

    def test_model_service_segment_untouched(self, settings_file: Path) -> None:
        """注册表改造不得影响既有的 model_service 段（AppConfig 取值来源）。"""
        _write(settings_file, {"model_service": {"llm_model": "flash", "llm_api_key": "sk-x"}})
        write_model_registry([dict(_OLD_ENTRY)], None)
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved["model_service"]["llm_model"] == "flash"
        assert saved["model_service"]["llm_api_key"] == "sk-x"
