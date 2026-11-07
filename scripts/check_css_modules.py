"""校验「组件用到的类名」都在它导入的 module（或全局层）里定义（2026-11-07）。

CSS Modules 的失败模式是**静默**的：类名写错或挂错文件，页面只是「没样式」。
这个脚本把 `className` 里的静态类名与 CSS 里的选择器对齐，错位就报出来。
动态拼接的类名（含 `${`）跳过——它们只能靠人工与截图核对。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLASS_DEF_RE = re.compile(r"^\.([a-zA-Z][\w-]*)", re.MULTILINE)
#: 历史遗留：JSX 里挂着、CSS 里从来没定义过的类（迁移前就无样式，非本次引入）。
LEGACY_UNSTYLED = {
    "clarify-card__kind",
    "clarify-option__mark",
    "clarify-option__text",
    "settings-error",
    "optimize-page__stop",
    "project-sidebar__more",
}
IMPORT_RE = re.compile(r"import \w+ from '(\.[^']*\.module\.css)'")
LITERAL_RE = re.compile(r"className=(?:\"([^\"]*)\"|\{s\('([^']*)'\)\})")


def classes_in(path: Path) -> set[str]:
    text = Path(path).read_text(encoding="utf-8")
    names: set[str] = set()
    for match in CLASS_DEF_RE.finditer(text):
        names.add(match.group(1))
        # `.a { }` 与 `.a:hover` / `.a .b` 都取到 a；组合选择器另起一行时可能漏，够用
    return names


def main(argv: list[str]) -> int:
    src = Path(next(a for a in argv[1:] if not a.startswith("--"))).resolve()
    global_classes = classes_in(src / "styles" / "global.css")
    problems: list[str] = []

    for tsx in sorted(src.rglob("*.tsx")):
        if tsx.name.endswith(".test.tsx") or "/lab/" in tsx.as_posix():
            continue
        text = tsx.read_text(encoding="utf-8")
        modules = IMPORT_RE.findall(text)
        if not modules:
            continue
        allowed = set(global_classes)
        missing: list[str] = []
        for rel in modules:
            module_path = (tsx.parent / rel).resolve()
            if not module_path.is_file():
                missing.append(rel)
                continue
            allowed |= classes_in(module_path)
        for rel in missing:
            problems.append(f"{tsx.name}: 导入的模块不存在 {rel}")
        if missing:
            continue
        for literal in LITERAL_RE.finditer(text):
            raw = literal.group(1) or literal.group(2) or ""
            for token in raw.split():
                if "${" in token or token == "":
                    continue
                if token in LEGACY_UNSTYLED:
                    continue
                if token not in allowed:
                    problems.append(f"{tsx.name}: 类名 {token} 不在 {module_path.name}/全局层")

    print("\n".join(problems) if problems else "全部类名都有定义")
    print(f"共 {len(problems)} 处问题")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
