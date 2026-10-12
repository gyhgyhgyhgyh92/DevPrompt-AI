"""导出 OpenAPI 契约到仓库根 openapi.json（T6-2 冻结接口）。

frontend `gen:contract` 消费 `../openapi.json`（阶段二冻结的跨阶段接口）；
导出物入库，`tests/api/test_openapi.py` 断言导出物与 app.openapi() 一致（契约冻结），
漂移时 CI 阻断——后端改字段必须重新运行本脚本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devprompt_ai.interfaces.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "openapi.json"


def export() -> dict[str, Any]:
    """生成 OpenAPI 文档（sort_keys 保证跨次导出稳定 diff）。"""
    doc: dict[str, Any] = create_app().openapi()
    return doc


def write(path: Path = OUT_PATH) -> Path:
    doc = export()
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    out = write()
    print(f"openapi.json 已导出：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
