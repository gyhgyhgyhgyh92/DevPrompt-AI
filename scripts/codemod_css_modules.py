"""一次性 codemod：把组件级 CSS 迁到 CSS Modules（2026-11-07）。

只做机械部分，判断留给测试与截图：
1) `import './X.css'` → `import styles from './X.module.css'` + `const s = makeS(styles)`；
2) `className="a b"` → `className={s('a b')}`；
3) `className={expr}` → `className={s(expr)}`，但跳过「本来就在 s(...) 里」与
   「直接透传 prop」两种情形（后者由组件内部自己拼，不能本地映射）。

不动：`main.tsx`（tokens/global 是全局层）、`src/lab/**`（Tailwind + dev-only 样式层）。

用法：`python scripts/codemod_css_modules.py frontend/src`（先跑 --dry 看清单）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS_IMPORT_RE = re.compile(r"^import '(\.[^']*\.css)'\n", re.MULTILINE)
PROP_CLASS_NAMES = {"className"}


def match_brace(src: str, open_index: int) -> int:
    """返回与 `{` 配对的 `}` 下标；跳过字符串 / 模板串 / 注释。"""
    depth = 0
    index = open_index
    while index < len(src):
        char = src[index]
        if char in "\"'`":
            quote = char
            index += 1
            while index < len(src):
                if src[index] == "\\":
                    index += 2
                    continue
                if src[index] == quote:
                    break
                index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("括号不配平")


def js_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def wrap_class_names(src: str) -> str:
    out: list[str] = []
    cursor = 0
    while True:
        found = src.find("className=", cursor)
        if found == -1:
            out.append(src[cursor:])
            return "".join(out)
        out.append(src[cursor:found])
        after = found + len("className=")
        marker = src[after] if after < len(src) else ""
        if marker in "\"'":
            end = src.find(marker, after + 1)
            value = src[after + 1 : end]
            out.append(f"className={{s({js_string(value)})}}")
            cursor = end + 1
        elif marker == "{":
            end = match_brace(src, after)
            expr = src[after + 1 : end]
            if expr.strip().startswith("s(") or expr.strip() in PROP_CLASS_NAMES:
                out.append(src[found : end + 1])
            else:
                out.append(f"className={{s({expr})}}")
            cursor = end + 1
        else:  # 理论不可达：保持原样
            out.append("className=")
            cursor = after
    return "".join(out)


def rel_helper(from_file: Path, src_root: Path) -> str:
    target = src_root / "utils" / "css"
    rel = Path(*target.parts[len(src_root.parts) :])
    depth = len(from_file.parent.parts) - len(src_root.parts)
    return "../" * depth + rel.as_posix()


def process(path: Path, src_root: Path, dry: bool) -> str | None:
    text = path.read_text(encoding="utf-8")
    imports = CSS_IMPORT_RE.findall(text)
    if not imports:
        return None
    if len(imports) > 1:
        raise SystemExit(f"{path}: 单个文件导入多个 CSS，需人工处理")
    css_rel = imports[0]
    before = text
    text = CSS_IMPORT_RE.sub(f"import styles from '{css_rel[:-4]}.module.css'\n", text, count=1)

    depth = len(path.parent.parts) - len(src_root.parts)
    helper = "../" * depth + "utils/css"
    text = text.replace(
        f"import styles from '{css_rel[:-4]}.module.css'\n",
        f"import styles from '{css_rel[:-4]}.module.css'\nimport {{ makeS }} from '{helper}'\n",
        1,
    )
    text = wrap_class_names(text)
    # helper 必须在组件定义之前：插在最后一条 import 之后
    lines = text.splitlines()
    last_import = max(
        (index for index, line in enumerate(lines) if line.startswith("import ")), default=-1
    )
    lines.insert(last_import + 1, "")
    lines.insert(last_import + 2, "const s = makeS(styles)")
    text = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    if not dry:
        path.write_text(text, encoding="utf-8", newline="\n")
    return f"{path.relative_to(src_root)} → {css_rel}"


def main(argv: list[str]) -> int:
    dry = "--dry" in argv
    src_root = Path(next(a for a in argv[1:] if not a.startswith("--"))).resolve()
    changed: list[str] = []
    for tsx in sorted(src_root.rglob("*.tsx")):
        if tsx.name.endswith(".test.tsx"):
            continue
        rel = tsx.relative_to(src_root).as_posix()
        if rel.startswith("lab/") or rel == "main.tsx":
            continue
        result = process(tsx, src_root, dry)
        if result is not None:
            changed.append(result)
    print("\n".join(changed))
    print(f"共 {len(changed)} 个文件{'（dry-run 未写入）' if dry else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
