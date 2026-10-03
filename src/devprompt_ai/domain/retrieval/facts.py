"""F-104 事实取证：ripgrep 逐项验证 7 项客观事实，布尔 + 证据，无「未知」。

证据截断 200 字符（MUST-09 精神：控制进入 state 的体积）。
I/O 全部经 CommandRunner / FileReader Protocol（MUST-06）。
"""

from __future__ import annotations

from devprompt_ai.domain.models import CodeLocation, FactResult
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader

_RG_ALLOWED = frozenset({0, 1})
_EVIDENCE_LIMIT = 200

_KNOWN_EXTS = {".tsx", ".ts", ".jsx", ".js", ".vue", ".py", ".css", ".scss", ".less", ".html"}


def _ev(raw: str) -> str:
    raw = raw.strip().replace("\n", " ⏎ ")
    return raw[:_EVIDENCE_LIMIT] if raw else "未找到"


async def verify_facts(
    location: CodeLocation, sentence: str, runner: CommandRunner, reader: FileReader
) -> list[FactResult]:
    """逐项验证七项事实（F-104 行为列）；每项独立验证，互不短路。"""
    path, name = location.path, location.symbol_name
    results: list[FactResult] = []

    # 1) 目标文件存在（文件系统检查经 FileReader）
    exists = await reader.exists(path)
    results.append(
        FactResult("target_file_exists", exists, f"file={path}" if exists else f"missing={path}")
    )

    # 2) 目标组件在文件中存在（rg 固定串搜索该文件）
    out = await runner.run(
        ["rg", "--fixed-strings", "-n", name, "--glob", path, ".", f"--route-key=symbol:{path}"],
        allowed_exit_codes=_RG_ALLOWED,
    )
    sym_hit = next((line for line in out.splitlines() if name in line), "")
    results.append(FactResult("symbol_in_file", bool(sym_hit), _ev(sym_hit)))

    # 3) 样式 token 已定义（全局搜 token 名的定义处，限定样式文件）
    token = location.tokens[0] if location.tokens else ""
    tok_out = (
        await runner.run(
            [
                "rg",
                "--fixed-strings",
                "-n",
                token,
                "--glob",
                "*.css",
                ".",
                f"--route-key=tokdef:{token}",
            ],
            allowed_exit_codes=_RG_ALLOWED,
        )
        if token
        else ""
    )
    tok_hit = next((line for line in tok_out.splitlines() if token and token in line), "")
    results.append(FactResult("token_defined", bool(tok_hit), _ev(tok_hit)))

    # 4) 组件含 data-testid（该文件内）
    out = await runner.run(
        ["rg", "-n", "data-testid", "--glob", path, ".", f"--route-key=testid:{path}"],
        allowed_exit_codes=_RG_ALLOWED,
    )
    tid = next((line for line in out.splitlines() if "data-testid" in line), "")
    results.append(FactResult("has_data_testid", bool(tid), _ev(tid)))

    # 5) 多状态样式（:hover / :focus / :active 任一）
    out = await runner.run(
        [
            "rg",
            "-n",
            "-e",
            ":hover",
            "-e",
            ":focus",
            "-e",
            ":active",
            "--glob",
            path,
            ".",
            f"--route-key=states:{path}",
        ],
        allowed_exit_codes=_RG_ALLOWED,
    )
    st = next(
        (
            line
            for line in out.splitlines()
            if any(s in line for s in (":hover", ":focus", ":active"))
        ),
        "",
    )
    results.append(FactResult("has_state_styles", bool(st), _ev(st)))

    # 6) 文件类型匹配预期（后缀在已知前端/样式后缀集内）
    last_seg = path.rsplit("/", 1)[-1]
    ext = ("." + last_seg.rsplit(".", 1)[-1]) if "." in last_seg else ""
    results.append(FactResult("file_type_matches", ext in _KNOWN_EXTS, f"ext={ext or 'none'}"))

    # 7) 关联测试文件存在（F-103 已定位的 test_paths 逐一存在性检查）
    test_evidence = "未找到"
    test_ok = False
    for tp in location.test_paths:
        if await reader.exists(tp):
            test_ok, test_evidence = True, f"test={tp}"
            break
    results.append(FactResult("test_file_exists", test_ok, test_evidence))

    return results
