"""§5.1 前端目录树：OpenAPI 导出入口（前端契约管线侧）。

实现在仓库根 ``scripts/export-openapi.py``（T6-2 冻结接口，由 pytest 复用），
本文件仅转发，保持 `frontend/scripts/` 与项目架构文档 §5.1 文件清单一致。
"""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT_EXPORTER = Path(__file__).resolve().parents[2] / "scripts" / "export-openapi.py"

if __name__ == "__main__":
    runpy.run_path(str(ROOT_EXPORTER), run_name="__main__")
