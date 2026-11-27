#!/usr/bin/env python3
"""版本号一致性检查：pyproject.toml / desktop/package.json / app.py。

自动更新器读取的是 Electron 的 desktop/package.json 版本，安装包元数据也由它生成；
sidecar 与 FastAPI 版本来自 pyproject/app.py。三处不一致会导致更新清单、UI 与健康检查
各说各话，因此放进 CI 硬失败。官网 links.ts 只做提示（发布前仍需人工同步）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def fastapi_version(text: str) -> str:
    match = re.search(r'FastAPI\([^)]*version="([^"]+)"', text, re.DOTALL)
    return match.group(1) if match is not None else ""


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = pyproject["project"]["version"]

    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    package_version = package["version"]

    app_text = (ROOT / "src" / "devprompt_ai" / "interfaces" / "api" / "app.py").read_text(
        encoding="utf-8"
    )
    app_version = fastapi_version(app_text)

    versions = {
        "pyproject.toml": pyproject_version,
        "desktop/package.json": package_version,
        "src/devprompt_ai/interfaces/api/app.py": app_version,
    }
    for source, version in versions.items():
        print(f"[check_versions] {source}: {version or '<missing>'}")

    unique = {version for version in versions.values() if version != ""}
    if "" in versions.values() or len(unique) != 1:
        print("[check_versions] FAIL: 版本号不一致或缺失", file=sys.stderr)
        return 1

    links_path = ROOT / "website" / "src" / "lib" / "links.ts"
    if links_path.exists():
        match = re.search(r'latest:\s*"([^"]+)"', links_path.read_text(encoding="utf-8"))
        if match is not None and match.group(1) != pyproject_version:
            print(
                f"[check_versions] WARN: website links.latest={match.group(1)}，"
                f"与项目版本 {pyproject_version} 不同",
                file=sys.stderr,
            )

    print(f"[check_versions] OK: {pyproject_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
