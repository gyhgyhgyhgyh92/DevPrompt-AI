"""错误码映射一致性检查测试（M-10）。

这是「配置漂移守卫」：后端 `domain/error_codes.py` 新增码而前端
`schemas/errorCodes.ts` 漏映射时，用户会看到未经整理的原始 message。
该漂移不引起任何运行时错误，只能靠静态比对拦住。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_arch", ROOT / "scripts" / "check_architecture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_arch"] = module
    spec.loader.exec_module(module)
    return module


_checker = _load_checker()


class TestRealRepoState:
    def test_current_repo_has_no_violations(self) -> None:
        """当前仓库必须通过——否则本测试自身失去意义。"""
        assert _checker.check_error_code_mapping() == []

    def test_covers_all_llm_failure_codes(self) -> None:
        """Batch 1 新增的 5011~5015 必须全在映射表里（前端要给精确文案）。"""
        import re

        ts = (ROOT / "frontend" / "src" / "schemas" / "errorCodes.ts").read_text(encoding="utf-8")
        for code in (5011, 5012, 5013, 5014, 5015):
            assert re.search(rf"^\s{{2}}{code}:", ts, re.MULTILINE), f"{code} 未映射"

    def test_success_code_is_not_mapped(self) -> None:
        """0 是成功码，正常路径不查表，不应出现在映射表里。"""
        import re

        ts = (ROOT / "frontend" / "src" / "schemas" / "errorCodes.ts").read_text(encoding="utf-8")
        assert not re.search(r"^\s{2}0:", ts, re.MULTILINE)


class TestDetectionLogic:
    def test_missing_backend_file_is_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文件缺失返回空而非报错——避免脚本在未初始化仓库里崩。"""
        monkeypatch.setattr(_checker, "ERROR_CODES_PY", tmp_path / "nope.py")
        monkeypatch.setattr(_checker, "ERROR_CODES_TS", tmp_path / "nope.ts")
        assert _checker.check_error_code_mapping() == []

    def test_detects_missing_mapping(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        py = tmp_path / "error_codes.py"
        py.write_text("ERROR_CODES = {\n    2001: 'a',\n    2002: 'b',\n}\n", encoding="utf-8")
        ts = tmp_path / "errorCodes.ts"
        ts.write_text("export const ERROR_TEXT = {\n  2001: '甲',\n}\n", encoding="utf-8")
        monkeypatch.setattr(_checker, "ERROR_CODES_PY", py)
        monkeypatch.setattr(_checker, "ERROR_CODES_TS", ts)

        violations = _checker.check_error_code_mapping()
        assert len(violations) == 1
        assert "2002" in violations[0]

    def test_allows_extra_frontend_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """前端可有多余兜底项——断言方向是子集而非相等。"""
        py = tmp_path / "error_codes.py"
        py.write_text("ERROR_CODES = {\n    2001: 'a',\n}\n", encoding="utf-8")
        ts = tmp_path / "errorCodes.ts"
        ts.write_text(
            "export const ERROR_TEXT = {\n  2001: '甲',\n  9999: '兜底',\n}\n", encoding="utf-8"
        )
        monkeypatch.setattr(_checker, "ERROR_CODES_PY", py)
        monkeypatch.setattr(_checker, "ERROR_CODES_TS", ts)
        assert _checker.check_error_code_mapping() == []
