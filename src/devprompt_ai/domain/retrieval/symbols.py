"""F-101 符号表构建：ctags JSON 解析（纯函数）+ 缓存键（纯函数，MUST-14）。

I/O（ctags 进程、stat 收集）在 harness 层；本模块可脱离文件系统与网络测试。

2026-11-11 增补：``parse_export_scan_output`` —— ctags 对 TSX 的顶层导出声明存在漏标
（实测：``export default function BookListPage()`` 在真实文件里不产出 tag，而把它单独
截取成小文件时又能产出），导致页面级组件根本无法进入候选集。改为用 rg 补扫一遍
顶层 ``export`` 声明做兜底合并。
"""

from __future__ import annotations

import json
import re

from devprompt_ai.common.hashing import sha256_hex
from devprompt_ai.domain.models import Symbol, SymbolKind

# ctags kind（u-ctags --output-format=json 输出全词 kind）→ SymbolKind 映射（未列出的归 other）
_KIND_MAP: dict[str, SymbolKind] = {
    "function": "function",
    "method": "function",
    "procedure": "function",
    "class": "class",
    "interface": "class",
    "struct": "class",
    "variable": "variable",
    "member": "variable",
    "property": "variable",
    "field": "variable",
    "constant": "variable",
    "local": "variable",
}

# F-101 排除目录（行为列一致）；.pnpm-store 为 pnpm 内容寻址缓存，
# 混入会使符号表膨胀两个数量级并污染候选集（真实项目实测）
EXCLUDED_DIRS: tuple[str, ...] = (
    ".pnpm-store",
    "node_modules",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
    ".devprompt-ai",
    ".logs",
)

#: 签名最大字符数：让排序证据块可控（MUST-09 state 压缩精神）。
#: 25 条候选 × 120 字符 ≈ 3KB，相对 max_state_tokens=30000 可接受。
SIGNATURE_LIMIT: int = 120


def _clean_signature(raw: object) -> str:
    """规范化 ctags 的 ``signature`` 字段：取首行 → 折叠空白 → 截断。

    ctags 给的是参数列表（可能跨多行、含嵌套括号）。只取首行并压空白，
    保证它对决策层是**一行可读**的判别信息，且体积可控（MUST-09 state 压缩）。
    """
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text:
        return ""
    first = text.splitlines()[0].strip()
    return " ".join(first.split())[:SIGNATURE_LIMIT]


def parse_ctags_output(raw: str) -> list[Symbol]:
    """解析 ctags --output-format=json 的逐行 JSON 输出；脏行与非 tag 行跳过。"""
    symbols: list[Symbol] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("_type") != "tag":
            continue
        name = obj.get("name")
        path = obj.get("path")
        raw_line = obj.get("line")
        if not name or not path or not isinstance(raw_line, int):
            continue
        kind = _KIND_MAP.get(str(obj.get("kind", "")), "other")
        # 路径归一化为 POSIX 相对形式（ctags 在 Windows 可能输出反斜杠）
        symbols.append(
            Symbol(
                name=str(name),
                path=str(path).replace("\\", "/").lstrip("./"),
                line=raw_line,
                kind=kind,
                signature=_clean_signature(obj.get("signature")),
            )
        )
    return symbols


def cache_key(project_root: str, mtimes: list[tuple[str, int]]) -> str:
    """符号表缓存键 = 项目绝对路径 + mtime 摘要（MUST-14，TTL 1 小时）。"""
    return sha256_hex(f"{project_root}\n{sorted(mtimes)}")[:16]


#: rg 补扫的源文件形态（与 ctags 的 ``--map-*`` 覆盖面保持接近）
_EXPORT_SCAN_GLOB = "*.{ts,tsx,js,jsx,mjs,cjs,vue}"

#: 顶层导出声明：``export [default] [async] function|class|const|let|var Name``
_EXPORT_NAME_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(function\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)"
)

_EXPORT_KEYWORD_KIND: dict[str, SymbolKind] = {
    "function": "function",
    "function*": "function",
    "class": "class",
    "const": "variable",
    "let": "variable",
    "var": "variable",
}


def build_export_scan_args(project_root: str) -> list[str]:
    """组装 rg 补扫命令：找顶层 ``export`` 声明（纯函数便于测试断言）。

    为什么必须补扫：ctags 6.1.0 对 TSX 会漏掉部分顶层导出（实测 ``export default
    function BookListPage()`` 无 tag），组件级符号缺失后，候选集只剩同文件里的
    ``export const`` 与后端 DTO，页面组件永远进不了前 25 名。
    """
    args = [
        "rg",
        "--no-heading",
        "--line-number",
        "--with-filename",
        "-e",
        r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+[A-Za-z_$]",
        "--glob",
        _EXPORT_SCAN_GLOB,
    ]
    for d in EXCLUDED_DIRS:
        args.extend(["--glob", f"!**/{d}/**"])
    args.append(project_root)
    return args


def parse_export_scan_output(raw: str) -> list[Symbol]:
    """解析 ``rg --no-heading --line-number`` 的 ``path:line:content`` 输出。

    只保留能从中解析出声明名的行；路径归一化为 POSIX 相对形式（与 ctags 侧一致）。
    """
    symbols: list[Symbol] = []
    for line in raw.splitlines():
        path, sep, rest = line.partition(":")
        if not sep:
            continue
        num_text, sep2, content = rest.partition(":")
        if not sep2 or not num_text.isdigit():
            continue
        match = _EXPORT_NAME_RE.match(content)
        if match is None:
            continue
        keyword, name = match.group(1), match.group(2)
        symbols.append(
            Symbol(
                name=name,
                path=path.replace("\\", "/").lstrip("./"),
                line=int(num_text),
                kind=_EXPORT_KEYWORD_KIND.get(keyword, "other"),
            )
        )
    return symbols


def build_ctags_args(project_root: str, *, with_signature: bool = True) -> list[str]:
    """组装 ctags 命令：JSON 输出 + 行号 + 排除目录（纯函数便于测试断言）。

    --map-TypeScript=+.tsx：本机 ctags 6.1.0 默认不映射 .tsx（实测零 tag），React/TSX 是主场景；
    --languages=-Markdown：md 标题会混入符号表污染候选名额，保持符号表 = 纯代码符号。

    --fields=+n+{signature}：签名（仅参数列表）是排序阶段唯一缺失的判别性上下文
    （W3 实测归因：候选仅含名称与路径，58% 排序准确率）。**仍不含函数体**（MUST-09 硬边界）。
    老版 ctags 不认 ``{signature}`` 会直接失败——调用方负责去掉该字段重试一次。
    """
    args = [
        "ctags",
        "-f",
        "-",
        "--output-format=json",
        "--fields=+n+{signature}" if with_signature else "--fields=+n",
        "--map-TypeScript=+.tsx",
        "--languages=-Markdown",
        "-R",
    ]
    for d in EXCLUDED_DIRS:
        args.append(f"--exclude={d}")
    args.append(project_root)
    return args
