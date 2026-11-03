"""OpenAPI 契约冻结测试（T6-2）：导出物与 app.openapi() 一致 + 18 操作在案（15 路径）。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from devprompt_ai.interfaces.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_export_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "export_openapi", REPO_ROOT / "scripts" / "export-openapi.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_openapi_covers_eighteen_operations() -> None:
    """15 路径 / 18 操作：preference/settings 各 GET+PUT，history PATCH+DELETE。

    2026-10-17 动态模型目录新增 2 操作（读取 + 刷新 `/settings/models/catalog`），
    下线，改走浏览器扩展 + native messaging），故再改为 **14/17**——BREAKING。
    2026-10-19 思考过程流式展示新增 `POST /optimize/stream`，改为 **15/18**（向后兼容，
    旧 `POST /optimize` 保留）。
    2026-11-01 项目级批量删除在既有 `/history` 路径上新增 DELETE 方法：路径数不变（14），
    操作数 16 → **17**。
    """
    doc = create_app().openapi()
    paths: dict[str, Any] = doc["paths"]
    assert len(paths) == 14
    assert all(p.startswith("/api/v1/") for p in paths)
    operations = sum(
        len([m for m in ops if m in {"get", "put", "post", "patch", "delete"}])
        for ops in paths.values()
    )
    assert operations == 17
    assert {"get", "delete"} <= set(paths["/api/v1/history"])
    assert "get" in paths["/api/v1/settings/models/catalog"]
    assert "post" in paths["/api/v1/settings/models/catalog/refresh"]
    assert set(paths["/api/v1/settings"]) >= {"get", "put"}
    assert {"patch", "delete"} <= set(paths["/api/v1/history/{session_id}"])
    # 多模型注册表（F-604，2026-10-13）：无新增路径，仅 /settings 契约增字段（防漏更）
    settings_schemas = doc["components"]["schemas"]
    assert "models" in settings_schemas["SettingsResponse"]["properties"]
    assert "models" in settings_schemas["SettingsUpdate"]["properties"]
    assert "active_model_id" in settings_schemas["SettingsUpdate"]["properties"]
    assert "ModelEntryView" in settings_schemas
    # 页内文件夹搜索（F-601，2026-10-13）：browse 条目含 rel_parent（无新增路径）


def test_settings_update_declares_put_semantics() -> None:
    """N-4：`models` 段的「整表替换」语义必须写进契约，否则调用方会误以为是 PATCH 合并。

    契约 description 是给 API 使用者的唯一入口；语义只存在于 docstring 代码里
    等于不存在——所以必须在 openapi 里显式声明。
    """
    doc = create_app().openapi()
    desc = doc["components"]["schemas"]["SettingsUpdate"]["description"]
    assert "整表替换" in desc
    assert "视为删除" in desc, "必须明确「未出现的条目视为删除」——这是最容易误解的点"
    assert "沿用" in desc, "api_key 空值语义（沿用旧值而非清空）也须声明"


def test_committed_openapi_matches_app() -> None:
    """契约冻结：入库 openapi.json 必须与当前 app.openapi() 一致（漂移即 CI 失败）。"""
    committed = json.loads((REPO_ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi()


def test_export_script_writes_stable_output(tmp_path: Path) -> None:
    """导出脚本两次产出 byte 级一致（diff 为零 = 冻结证据）。"""
    mod = _load_export_module()
    first = mod.write(tmp_path / "a.json")
    second = mod.write(tmp_path / "b.json")
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    doc = json.loads(first.read_text(encoding="utf-8"))
    assert doc["info"]["title"] == "DevPrompt AI"


class TestContextWindowTierContract:
    """上下文窗口档位契约（2026-09-17）。

    档位是「用户可单选」的受限集合——必须随 provider 目录下发，且不得
    超过厂商标称窗口（否则用户得到假安全感）。
    """

    def test_provider_directory_carries_tiers(self) -> None:
        props = create_app().openapi()["components"]["schemas"]["ProviderDirectoryEntry"][
            "properties"
        ]
        assert "context_window_tiers" in props
        assert "max_context_length" in props, "标称窗口须与档位同段下发"

    def test_entry_view_exposes_override(self) -> None:
        props = create_app().openapi()["components"]["schemas"]["ModelEntryView"]["properties"]
        assert "max_context_length" in props, "每条目可选档位"

    def test_entry_update_accepts_override(self) -> None:
        props = create_app().openapi()["components"]["schemas"]["ModelEntryUpdate"]["properties"]
        assert "max_context_length" in props

    def test_removed_param_overrides_absent(self) -> None:
        """参数编辑区已下线，契约不应再暴露param_overrides。"""
        doc = create_app().openapi()["components"]["schemas"]
        for name in ("ModelEntryView", "ModelEntryUpdate"):
            assert "param_overrides" not in doc[name]["properties"], name

    def test_model_specs_segment_removed(self) -> None:
        """参数定义契约段随参数编辑区一并下线。"""
        doc = create_app().openapi()["components"]["schemas"]
        assert "model_specs" not in doc["SettingsResponse"]["properties"]
        assert "ParameterDefinitionView" not in doc

    def test_path_and_operation_count_unchanged(self) -> None:
        """档位契约改动**不新增路径**（2026-10-17）；2026-10-19 删除 browse 后为 14/17，
        同日新增 /optimize/stream 后为 15/18；2026-11-01 项目级批量删除挂在既有
        `/history` 路径上，故仍为 14 路径 / 17 操作。"""
        doc = create_app().openapi()
        assert len(doc["paths"]) == 14
        operations = sum(
            len([k for k in v if k in {"get", "post", "put", "patch", "delete"}])
            for v in doc["paths"].values()
        )
        assert operations == 17
