"""F-103 全文定位：rg 定位定义行号，文件内容提取选择器与设计 token，命名约定找测试。

I/O 全部经 CommandRunner / FileReader Protocol（MUST-06）。
测试路由键约定：rg 参数中的 --route-key=<键> 仅被测试 Fake 识别，
LocalCommandRunner 在转发真实进程前会过滤掉它（见 common/process.py 的 run_command）。
"""

from __future__ import annotations

import json
import posixpath
import re

from devprompt_ai.domain.models import CodeLocation, Symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader

_RG_ALLOWED = frozenset({0, 1})  # 1 = 无匹配（rg 语义，正常）

_CLASS_RE = re.compile(r"""(?:className|class)\s*=\s*["'{]([^"'}]+)["'}]""")
_TOKEN_RE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*")


def _with_route(args: list[str], key: str) -> list[str]:
    """在真实 rg 参数后追加测试路由键（LocalCommandRunner 转发前过滤）。"""
    return [*args, f"--route-key={key}"]


async def locate_symbol(
    symbol: Symbol, runner: CommandRunner, reader: FileReader, *, root: str = "."
) -> CodeLocation:
    """定位符号：定义行号（rg 首个精确匹配）+ 选择器/token（读文件正则提取）。

    关联测试文件按命名约定对候选路径做存在性检查。
    root：目标项目根（Symbol.path 为仓库相对路径，FileReader 文件系统访问需拼接——
    进程 cwd 是 DevPrompt AI 自身而非目标项目，4H 端到端实测暴露）。
    """

    def _fs(rel: str) -> str:
        return posixpath.join(root, rel) if root not in (".", "") else rel

    # 1) 定义行号：rg --json 固定串搜索限定该文件
    def_args = _with_route(
        [
            "rg",
            "--json",
            "-n",
            "--no-heading",
            "--fixed-strings",
            symbol.name,
            "--glob",
            symbol.path,
            ".",
        ],
        f"def:{symbol.name}",
    )
    # cwd 必须是项目根：进程 cwd 是本工具自身仓库，`--glob 相对路径` 否则永不命中
    raw = await runner.run(
        def_args, allowed_exit_codes=_RG_ALLOWED, cwd=None if root in (".", "") else root
    )
    definition_line = _first_match_line(raw)

    # 2) 选择器与设计 token：读文件文本正则提取
    text = await reader.read(_fs(symbol.path))
    selectors: list[str] = []
    for m in _CLASS_RE.finditer(text):
        for cls in m.group(1).replace("'", " ").replace('"', " ").split():
            if cls and cls not in selectors:
                selectors.append(cls)

    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        if tok not in tokens:
            tokens.append(tok)

    # 3) 关联测试文件：按命名约定对候选路径做存在性检查
    test_paths: list[str] = []
    stem, dot, ext = symbol.path.rpartition(".")
    base = stem if dot else symbol.path
    file_name = symbol.path.rsplit("/", 1)[-1]
    ext_clean = ext if dot else "ts"
    candidates = [
        f"{base}.test.{ext_clean}",
        f"{base}.spec.{ext_clean}",
        f"test_{file_name}",
        f"{base}_test.{ext_clean}",
    ]
    for cand in candidates:
        if await reader.exists(_fs(cand)):
            test_paths.append(cand)

    return CodeLocation(
        symbol_name=symbol.name,
        path=symbol.path,
        definition_line=definition_line,
        selectors=selectors,
        tokens=tokens,
        test_paths=test_paths,
    )


def _first_match_line(rg_json: str) -> int:
    """从 rg --json 输出提取首个匹配行号；无匹配返回 0（F-104 的 symbol_in_file 会标 fail）。"""
    for line in rg_json.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "match":
            ln = obj.get("data", {}).get("line_number")
            if isinstance(ln, int):
                return ln
    return 0
