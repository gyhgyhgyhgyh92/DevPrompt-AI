"""Python 符号图（I4）：标准库 `ast` 抽取符号、导入与调用。

为什么不用 tree-sitter：本项目主语言是 Python，`ast` 零依赖且语义精确；
其它语言继续沿用 ctags 签名，不强行统一。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Final

_SIGNATURE_LIMIT: Final[int] = 120


@dataclass(frozen=True, slots=True)
class SymbolDef:
    name: str
    kind: str
    line: int
    end_line: int
    signature: str = ""


@dataclass(frozen=True, slots=True)
class ParsedFile:
    path: str
    symbols: tuple[SymbolDef, ...] = ()
    imports: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.args]
    return f"{node.name}({', '.join(args)})"[:_SIGNATURE_LIMIT]


def _end_line(node: ast.AST, fallback: int) -> int:
    return int(getattr(node, "end_lineno", fallback) or fallback)


def parse_python(path: str, source: str) -> ParsedFile:
    """解析单个文件；语法错误返回空符号 + 错误信息，不抛异常。"""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return ParsedFile(path=path, errors=(f"syntax:{exc.lineno}",))

    symbols: list[SymbolDef] = []
    imports: set[str] = set()
    calls: set[str] = set()

    def visit(node: ast.AST, *, in_class: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                SymbolDef(
                    name=node.name,
                    kind="method" if in_class else "function",
                    line=node.lineno,
                    end_line=_end_line(node, node.lineno),
                    signature=_signature(node),
                )
            )
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    _record_call(child, calls)
            return
        if isinstance(node, ast.ClassDef):
            symbols.append(
                SymbolDef(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    end_line=_end_line(node, node.lineno),
                )
            )
            for child in node.body:
                visit(child, in_class=True)
            return
        if isinstance(node, ast.Import):
            # 保留完整模块名：`import pkg.mod` 要能解析到 pkg/mod.py，截断成 pkg 会连错边
            imports.update(alias.name for alias in node.names)
            return
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, in_class=in_class)

    for node in tree.body:
        visit(node)
    return ParsedFile(
        path=path,
        symbols=tuple(symbols),
        imports=tuple(sorted(imports)),
        calls=tuple(sorted(calls)),
    )


def _record_call(node: ast.Call, calls: set[str]) -> None:
    func = node.func
    if isinstance(func, ast.Name):
        calls.add(func.id)
    elif isinstance(func, ast.Attribute):
        calls.add(func.attr)


def import_edges(parsed: ParsedFile, known_paths: set[str]) -> list[tuple[str, str]]:
    """把 `import x` 解析为文件边：`pkg/mod.py` 命中才连边，解析不出就跳过。"""
    edges: list[tuple[str, str]] = []
    for module in parsed.imports:
        base = module.replace(".", "/")
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            if candidate in known_paths:
                edges.append((parsed.path, candidate))
                break
    return edges
