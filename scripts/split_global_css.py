"""把 global.css 拆成「全局层 / 壳层 / 工作台页面层」（2026-11-07 CSS Modules 迁移配套）。

分类规则（按选择器前缀）：
- 壳层 `SHELL_PREFIXES` → App.module.css（App.tsx 唯一消费者）
- 工作台 `PAGE_PREFIXES` → pages/OptimizePage.module.css（OptimizePage 唯一消费者）
- 其余留在 styles/global.css（reset、基础排版、跨组件原语：.button/.field/.ask-panel/…）

@layer / @media 内外都会被递归处理；混合内容的 @media 会拆成两个同名媒体查询。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SHELL_PREFIXES = (".app-", ".api-pill")
PAGE_PREFIXES = (".workspace", ".optimize-page", ".thread__")

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def split_blocks(css: str) -> list[str]:
    """按顶层 `{...}` 切块（注释与字符串里的花括号不参与计数）。"""
    blocks: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(css):
        char = css[index]
        if css.startswith("/*", index):
            end = css.find("*/", index + 2)
            index = len(css) if end == -1 else end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
        if depth == 0 and char == "}":
            blocks.append(css[start:index])
            start = index
    if start < len(css):
        blocks.append(css[start:])
    return blocks


def selector_of(block: str) -> str:
    brace = block.find("{")
    return block[:brace] if brace != -1 else ""


def classify(selector: str) -> str:
    text = COMMENT_RE.sub("", selector).strip()
    if any(prefix in text for prefix in SHELL_PREFIXES):
        return "shell"
    if any(prefix in text for prefix in PAGE_PREFIXES):
        return "page"
    return "global"


def split_media(block: str) -> dict[str, list[str]]:
    """把 @media 内的规则按分类拆开；返回 {分类: [规则文本]}。"""
    head_end = block.find("{")
    head = block[: head_end + 1]
    body = block[head_end + 1 : block.rstrip().rfind("}")]
    grouped: dict[str, list[str]] = {}
    for inner in split_blocks(body):
        if inner.strip() == "":
            continue
        grouped.setdefault(classify(selector_of(inner)), []).append(inner)
    return {kind: [head, *rules, "}\n"] for kind, rules in grouped.items()}


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    root = Path(next(a for a in argv[1:] if not a.startswith("--"))).resolve()
    global_css = root / "styles" / "global.css"
    text = global_css.read_text(encoding="utf-8")

    buckets: dict[str, list[str]] = {"global": [], "shell": [], "page": []}
    for block in split_blocks(text):
        if block.strip() == "":
            continue
        selector = COMMENT_RE.sub("", selector_of(block)).strip()
        if selector.startswith("@media"):
            for kind, parts in split_media(block).items():
                buckets[kind].append("".join(parts))
            continue
        buckets[classify(selector)].append(block)

    shell_css = "".join(buckets["shell"]).strip()
    page_css = "".join(buckets["page"]).strip()
    rest = "".join(buckets["global"]).strip()

    print(f"全局层 {len(buckets['global'])} 块 / 壳层 {len(buckets['shell'])} 块 / 页面层 {len(buckets['page'])} 块")
    if not apply:
        print("dry-run：加 --apply 才写文件")
        return 0

    (root / "App.module.css").write_text(shell_css + "\n", encoding="utf-8", newline="\n")
    (root / "pages" / "OptimizePage.module.css").write_text(
        "/* 工作台页面层（2026-11-07 从 global.css 迁出）：仅 OptimizePage 使用。 */\n"
        + page_css
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    global_css.write_text(rest + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
