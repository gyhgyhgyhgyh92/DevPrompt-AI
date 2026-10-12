"""OpenAPI 契约冻结测试（T6-2）：导出物与 app.openapi() 一致 + 16 操作在案（13 路径）。"""

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


def test_openapi_covers_sixteen_operations() -> None:
    """13 路径 / 16 操作：preference/settings 各 GET+PUT，history PATCH+DELETE，project pick。"""
    doc = create_app().openapi()
    paths: dict[str, Any] = doc["paths"]
    assert len(paths) == 13
    assert all(p.startswith("/api/v1/") for p in paths)
    operations = sum(
        len([m for m in ops if m in {"get", "put", "post", "patch", "delete"}])
        for ops in paths.values()
    )
    assert operations == 16
    assert set(paths["/api/v1/settings"]) >= {"get", "put"}
    assert set(paths["/api/v1/preference"]) >= {"get", "put"}
    assert "delete" in paths["/api/v1/preference/adoptions"]
    assert {"patch", "delete"} <= set(paths["/api/v1/history/{session_id}"])
    assert "post" in paths["/api/v1/project/pick"]


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
