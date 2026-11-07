"""设计 token 对比度审计（2026-11-07）。

为什么需要：MUST-08 要求「前端不出现阈值」，但**对比度阈值本身**必须有人守——此前换肤
只靠肉眼与样张页抽查，深色主题尤其容易漏。本脚本直接解析 `styles/tokens.css`，
把每个必需的「文字/背景」配对按 WCAG 2.1 公式算一遍，低于门槛即 exit 1。

口径：
- 正文类文本（≥13px 常规字重）要求 **4.5:1**（AA）
- 图标/描边/大号文本等 UI 元件要求 **3:1**（AA，1.4.11）
- 边框类单独用 `ADVISORY` 标注：发丝线刻意低对比，不参与 fail

用法：`python scripts/audit_contrast.py [--verbose]`
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOKENS = Path("frontend/src/styles/tokens.css")

BLOCKS = {
    "light": r":root,\s*\[data-theme='light'\]\s*\{(?P<body>[^}]*)\}",
    "dark": r"\[data-theme='dark'\]\s*\{(?P<body>[^}]*)\}",
}

Pair = tuple[str, str]
TEXT_PAIRS: list[Pair] = [
    ("--color-text-primary", "--color-surface-base"),
    ("--color-text-primary", "--color-surface-raised"),
    ("--color-text-primary", "--color-surface-code"),
    ("--color-text-secondary", "--color-surface-base"),
    ("--color-text-secondary", "--color-surface-raised"),
    ("--color-text-muted", "--color-surface-base"),
    ("--color-text-muted", "--color-surface-raised"),
    # 语义色在组件里被当作小字文本使用（「已完成」「复制成功」「失败原因」），必须按正文口径算
    ("--color-success-500", "--color-surface-base"),
    ("--color-running-500", "--color-surface-base"),
    ("--color-danger-500", "--color-surface-base"),
    ("--text-faint", "--color-surface-base"),
]
UI_PAIRS: list[Pair] = [
    ("--color-primary-500", "--color-surface-base"),
    ("--color-primary-700", "--color-surface-base"),
    ("--color-text-inverse", "--color-primary-500"),
    ("--color-success-500", "--color-surface-base"),
    ("--color-running-500", "--color-surface-base"),
    ("--color-danger-500", "--color-surface-base"),
    ("--color-warning-500", "--color-surface-base"),
    ("--color-primary-700", "--color-primary-soft"),
    # 可交互控件的轮廓（WCAG 1.4.11）：输入框、按钮、下拉、选项卡的 1px 描边
    ("--color-border-control", "--color-surface-base"),
    ("--color-border-control", "--color-surface-raised"),
]
ADVISORY_PAIRS: list[Pair] = [
    ("--color-border-strong", "--color-surface-base"),
    ("--color-border-subtle", "--color-surface-base"),
    ("--text-faint", "--color-surface-base"),
]

TEXT_MIN = 4.5
UI_MIN = 3.0


def load_blocks() -> dict[str, dict[str, str]]:
    text = TOKENS.read_text(encoding="utf-8")
    result: dict[str, dict[str, str]] = {}
    for theme, pattern in BLOCKS.items():
        match = re.search(pattern, text, re.S)
        if match is None:
            raise SystemExit(f"找不到 {theme} 主题的 token 块：{TOKENS}")
        body = match.group("body")
        result[theme] = {
            name: value.strip()
            for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", body)
        }
    return result


def parse_color(value: str) -> tuple[int, int, int, float] | None:
    value = value.strip()
    hex_match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if hex_match:
        body = hex_match.group(1)
        if len(body) == 3:
            body = "".join(char * 2 for char in body)
        return (
            int(body[0:2], 16),
            int(body[2:4], 16),
            int(body[4:6], 16),
            1.0,
        )
    rgb_match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if rgb_match:
        parts = [part.strip() for part in re.split(r"[,\s/]+", rgb_match.group(1)) if part]
        if len(parts) < 3:
            return None
        channels = [int(round(float(part.rstrip("%")) if part.endswith("%") else float(part)))
                    for part in parts[:3]]
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return (channels[0], channels[1], channels[2], alpha)
    return None


def resolve(name: str, tokens: dict[str, str], depth: int = 0) -> str:
    """把 `var(--x)` 链解析成具体色值；解析不到原样返回（交给 parse 判空）。"""
    if depth > 8:
        raise SystemExit(f"var() 嵌套过深：{name}")
    raw = tokens.get(name)
    if raw is None:
        raise SystemExit(f"token 未定义：{name}")
    var_match = re.fullmatch(r"var\((--[\w-]+)\)", raw)
    if var_match:
        return resolve(var_match.group(1), tokens, depth + 1)
    return raw


def composite(foreground: tuple[int, int, int, float], background: tuple[int, int, int, float]) -> tuple[int, int, int, float]:
    alpha = foreground[3]
    mixed = tuple(
        round(foreground[index] * alpha + background[index] * (1 - alpha)) for index in range(3)
    )
    return (mixed[0], mixed[1], mixed[2], 1.0)


def luminance(color: tuple[int, int, int, float]) -> float:
    def channel(value: int) -> float:
        scaled = value / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def ratio(
    foreground: tuple[int, int, int, float],
    background: tuple[int, int, int, float],
    canvas: tuple[int, int, int, float],
) -> float:
    """半透明前景/背景都先叠到 canvas 上再算（深色主题的 soft 色全是 rgba）。"""
    back = composite(background, canvas) if background[3] < 1 else background
    front = composite(foreground, back) if foreground[3] < 1 else foreground
    a, b = luminance(front), luminance(back)
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


def audit(theme: str, tokens: dict[str, str], verbose: bool) -> list[str]:
    failures: list[str] = []
    canvas = parse_color(resolve("--color-surface-base", tokens))
    if canvas is None:
        raise SystemExit(f"{theme}: --color-surface-base 无法解析")
    groups = (
        ("文本", TEXT_PAIRS, TEXT_MIN),
        ("UI 元件", UI_PAIRS, UI_MIN),
        ("参考（不计失败）", ADVISORY_PAIRS, UI_MIN),
    )
    print(f"\n=== {theme} ===")
    for label, pairs, threshold in groups:
        print(f"-- {label}（门槛 {threshold}:1）")
        for foreground, background in pairs:
            front = parse_color(resolve(foreground, tokens))
            back = parse_color(resolve(background, tokens))
            if front is None or back is None:
                failures.append(f"{theme}: {foreground} / {background} 色值无法解析")
                continue
            value = ratio(front, back, canvas)
            is_advisory = label.startswith("参考")
            passed = value >= threshold
            mark = "OK " if passed else ("LOW" if is_advisory else "FAIL")
            if not passed and not is_advisory:
                failures.append(
                    f"{theme}: {foreground} / {background} = {value:.2f}:1 < {threshold}:1"
                )
            if verbose or not passed:
                print(f"   {mark} {value:5.2f}:1  {foreground} / {background}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="打印全部配对，而不只低分项")
    args = parser.parse_args()

    if not TOKENS.exists():
        print(f"找不到 {TOKENS}（请在仓库根目录执行）")
        return 2

    blocks = load_blocks()
    failures: list[str] = []
    for theme in ("light", "dark"):
        failures.extend(audit(theme, blocks[theme], args.verbose))

    if failures:
        print("\n对比度审计未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n对比度审计通过：所有必需配对均达到 WCAG AA 门槛。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
