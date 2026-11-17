"""把测试里的类选择器改为「类名包含」选择器（2026-11-07 CSS Modules 迁移配套）。

CSS Modules 会把 `chat-user-bubble` 变成 `_chat-user-bubble_ab12`，原选择器 `.chat-user-bubble`
不再命中。测试只关心「这个角色存在」，不关心精确类名，故统一改为 `[class*="chat-user-bubble"]`。

只处理 querySelector / querySelectorAll / closest 三个 API 的字符串字面量实参；
其余断言（className 全等、getAttribute('class')）人工改，避免误伤。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CALLS = ("querySelectorAll", "querySelector", "closest")
CLASS_TOKEN = re.compile(r"\.([A-Za-z][\w-]*)")


def convert(selector: str) -> str:
    if not selector.startswith(".") and " ." not in selector:
        return selector
    return CLASS_TOKEN.sub(lambda m: f'[class*="{m.group(1)}"]', selector)


def rewrite(text: str) -> tuple[str, int]:
    count = 0
    for call in CALLS:
        cursor = 0
        while True:
            found = text.find(f"{call}('", cursor)
            if found == -1:
                break
            start = found + len(call) + 2
            end = text.find("'", start)
            selector = text[start:end]
            converted = convert(selector)
            if converted != selector:
                text = text[:start] + converted + text[end:]
                count += 1
            cursor = start + len(converted)
    return text, count


def main(argv: list[str]) -> int:
    src = Path(next(a for a in argv[1:] if not a.startswith("--"))).resolve()
    total = 0
    for path in sorted(src.rglob("*.test.tsx")) + sorted(src.rglob("*.test.ts")):
        text = path.read_text(encoding="utf-8")
        updated, count = rewrite(text)
        if count:
            path.write_text(updated, encoding="utf-8", newline="\n")
            total += count
            print(f"{path.name}: {count}")
    print(f"共替换 {total} 处选择器")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
