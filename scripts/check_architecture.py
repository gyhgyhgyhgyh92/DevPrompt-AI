"""架构约束静态检查（宪法 MUST-06 / MUST-08、架构文档附录 B）。

检查项：
1. domain/ 不得 import 表现层与服务层实现模块（MUST-06）
2. service.py / state.py 不得反向 import interfaces/（MUST-06）
3. SQL 字符串不得出现在 memory/ 之外（MUST-06）
4. 前端 ts/tsx 不得出现阈值常量（MUST-08）
5. 组件文件名必须与主导出名一致（架构文档 §5.3）
6. interfaces/api/ 不得 import harness/memory/decision/state 实现模块（Web 薄壳约束，MUST-06）

退出码：0 = 通过；1 = 存在违规。
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path("src/devprompt_ai")
FRONTEND_SRC = Path("frontend/src")

DOMAIN_FORBIDDEN = (
    "devprompt_ai.interfaces",
    "devprompt_ai.harness",
    "devprompt_ai.memory",
    "devprompt_ai.decision",
    "devprompt_ai.service",
    "devprompt_ai.state",
    "devprompt_ai.config",
    "devprompt_ai.main",
    "devprompt_ai.observability",
)
SERVICE_FORBIDDEN = ("devprompt_ai.interfaces",)
API_FORBIDDEN = (
    "devprompt_ai.harness",
    "devprompt_ai.memory",
    "devprompt_ai.decision",
    "devprompt_ai.state",
)

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)
SQL_RE = re.compile(
    r"\b(?:SELECT\b|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|CREATE\s+TABLE\b)",
    re.IGNORECASE,
)
THRESHOLD_RE = re.compile(r"\b0\.12\b|\b0\.5\b|\bthresholds?\b", re.IGNORECASE)


def check_domain_imports() -> list[str]:
    violations: list[str] = []
    domain_dir = SRC / "domain"
    if not domain_dir.exists():
        return violations
    for py in sorted(domain_dir.rglob("*.py")):
        for match in IMPORT_RE.finditer(py.read_text(encoding="utf-8")):
            module = match.group(1)
            if module.startswith("devprompt_ai.domain") or not module.startswith("devprompt_ai"):
                continue
            if module.startswith(DOMAIN_FORBIDDEN):
                violations.append(f"[MUST-06] {py}: import '{module}'")
    return violations


def check_service_imports() -> list[str]:
    violations: list[str] = []
    for name in ("service.py", "state.py"):
        py = SRC / name
        if not py.exists():
            continue
        for match in IMPORT_RE.finditer(py.read_text(encoding="utf-8")):
            module = match.group(1)
            if module.startswith(SERVICE_FORBIDDEN):
                violations.append(f"[MUST-06] {py}: import '{module}'")
    return violations


def check_api_imports() -> list[str]:
    violations: list[str] = []
    api_dir = SRC / "interfaces" / "api"
    if not api_dir.exists():
        return violations
    for py in sorted(api_dir.rglob("*.py")):
        for match in IMPORT_RE.finditer(py.read_text(encoding="utf-8")):
            module = match.group(1)
            if module.startswith(API_FORBIDDEN):
                violations.append(f"[MUST-06] {py}: import '{module}'")
    return violations


def check_sql_outside_memory() -> list[str]:
    violations: list[str] = []
    if not SRC.exists():
        return violations
    memory_dir = (SRC / "memory").resolve()
    for py in sorted(SRC.rglob("*.py")):
        if py.resolve().is_relative_to(memory_dir):
            continue
        if SQL_RE.search(py.read_text(encoding="utf-8")):
            violations.append(f"[MUST-06] {py}: 疑似 SQL 出现在 memory/ 之外")
    return violations


def check_frontend_thresholds() -> list[str]:
    violations: list[str] = []
    if not FRONTEND_SRC.exists():
        return violations
    generated = FRONTEND_SRC / "schemas" / "openapi.generated.ts"
    for pattern in ("*.ts", "*.tsx"):
        for f in sorted(FRONTEND_SRC.rglob(pattern)):
            if f == generated:
                continue  # 契约镜像产物，非业务代码（F-705）
            for match in THRESHOLD_RE.finditer(f.read_text(encoding="utf-8")):
                violations.append(f"[MUST-08] {f}: 疑似阈值常量 '{match.group(0)}'")
    return violations


def check_component_names() -> list[str]:
    violations: list[str] = []
    component_dir = FRONTEND_SRC / "components"
    if not component_dir.exists():
        return violations
    for f in sorted(component_dir.rglob("*.tsx")):
        expected = f.stem
        if "." in expected:
            continue  # 测试文件（*.test.tsx 等）非组件，不适用「文件名=主导出名」（§5.3）
        export_re = re.compile(
            rf"export\s+(?:default\s+)?(?:function|const)\s+{expected}\b"
            rf"|export\s+default\s+{expected}\b"
        )
        if not export_re.search(f.read_text(encoding="utf-8")):
            violations.append(f"[§5.3] {f}: 文件名与主导出名不一致（期望导出 {expected}）")
    return violations


def main() -> int:
    violations = (
        check_domain_imports()
        + check_service_imports()
        + check_api_imports()
        + check_sql_outside_memory()
        + check_frontend_thresholds()
        + check_component_names()
    )
    if violations:
        print("架构约束检查未通过：")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("架构约束检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
