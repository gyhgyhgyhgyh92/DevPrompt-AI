"""构建脚本契约测试（N-2）。

借鉴 prompt-optimizer `scripts/package-scripts.test.mjs`：把「门禁必须包含哪些子检查」
写成断言，避免重构配置文件时质量门禁被静默丢失。本测试只读文件，不执行构建。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_JSON = ROOT / "frontend" / "package.json"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _pyproject_text() -> str:
    """读 pyproject 原文。

    刻意不用 tomllib 解析：mypy 以 python_version=3.10 为准，而 tomllib 是 3.11+
    标准库（无 stub 会报 missing-imports）。契约测试只需关键字存在性，正则足够。
    """
    return PYPROJECT.read_text(encoding="utf-8")


def _frontend_scripts() -> dict[str, str]:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    return {str(k): str(v) for k, v in scripts.items()}


class TestPyprojectContracts:
    def test_console_script_registered(self) -> None:
        assert "[project.scripts]" in _pyproject_text()
        assert 'devprompt-ai = "devprompt_ai.main:main"' in _pyproject_text()

    def test_mypy_covers_src_tests_scripts(self) -> None:
        text = _pyproject_text()
        assert re.search(r"\[tool\.mypy\]", text) is not None
        assert re.search(r"strict\s*=\s*true", text) is not None
        files_match = re.search(r"files\s*=\s*\[([^\]]*)\]", text)
        assert files_match is not None, "mypy 未声明 files"
        declared = {item.strip().strip('"') for item in files_match.group(1).split(",")}
        assert {"src", "tests", "scripts"} <= declared

    def test_ruff_enables_async_rules(self) -> None:
        """MUST-13：ASYNC 规则组必须开启，否则阻塞调用不会被拦。"""
        select_match = re.search(r"select\s*=\s*\[([^\]]*)\]", _pyproject_text())
        assert select_match is not None, "ruff 未声明 lint.select"
        assert "ASYNC" in select_match.group(1)

    def test_pytest_asyncio_auto_mode(self) -> None:
        """异步测试须为 auto 模式，否则全部被跳过（假绿）。"""
        assert re.search(r'asyncio_mode\s*=\s*"auto"', _pyproject_text()) is not None


class TestFrontendScriptContracts:
    def test_required_scripts_present(self) -> None:
        scripts = _frontend_scripts()
        required = ("build", "typecheck", "lint", "format:check", "test", "check:contract")
        for name in required:
            assert name in scripts, f"frontend/package.json 缺少脚本：{name}"

    def test_check_contract_has_generation_and_diff_gate(self) -> None:
        """契约管线必须「重新生成 + git diff 阻断」两步齐全。"""
        script = _frontend_scripts()["check:contract"]
        assert "gen:contract" in script
        assert "git diff --exit-code" in script

    def test_no_paths_alias_shortcut(self) -> None:
        """禁止用 paths 别名把契约类型指回源码——必须验证真实生成产物。"""
        assert '"paths"' not in PACKAGE_JSON.read_text(encoding="utf-8")

    def test_tsconfig_has_no_alias_to_src(self) -> None:
        for tsconfig in (ROOT / "frontend").glob("tsconfig*.json"):
            raw = tsconfig.read_text(encoding="utf-8")
            pattern = r'"paths"\s*:\s*\{'
            assert re.search(pattern, raw) is None, tsconfig.name + " 含 paths 别名"


class TestCiWorkflowContracts:
    def test_all_gates_present(self) -> None:
        """CI 必须实跑全部门禁，缺一即视为门禁名存实亡。"""
        content = CI_YML.read_text(encoding="utf-8")
        required = (
            "ruff check",
            "ruff format --check",
            "uv run mypy",
            "uv run pytest",
            "pnpm build",
            "pnpm typecheck",
            "pnpm lint",
            "pnpm format:check",
            "pnpm test",
            "pnpm check:contract",
            "check_architecture.py",
        )
        missing = [name for name in required if name not in content]
        assert not missing, f"CI 缺少门禁：{missing}"

    def test_uses_frozen_lockfile(self) -> None:
        """MUST-24：依赖必须锁文件安装，禁止漂移。"""
        content = CI_YML.read_text(encoding="utf-8")
        assert "uv sync --frozen" in content
        assert "pnpm install --frozen-lockfile" in content

    def test_architecture_job_is_separate(self) -> None:
        content = CI_YML.read_text(encoding="utf-8")
        assert re.search(r"^  architecture:", content, re.MULTILINE)
