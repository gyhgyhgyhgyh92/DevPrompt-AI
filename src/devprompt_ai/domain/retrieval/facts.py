"""F-104 事实取证：ripgrep 逐项验证 7 项客观事实，布尔 + 证据，无「未知」。

证据截断 200 字符（MUST-09 精神：控制进入 state 的体积）。
I/O 全部经 CommandRunner / FileReader Protocol（MUST-06）。
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence

from devprompt_ai.domain.models import CodeLocation, FactResult
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader

_RG_ALLOWED = frozenset({0, 1})
_EVIDENCE_LIMIT = 200

_KNOWN_EXTS = {".tsx", ".ts", ".jsx", ".js", ".vue", ".py", ".css", ".scss", ".less", ".html"}

#: 前端/样式后缀：只有这类目标文件才可能同时具备 token / testid / 状态样式
_FRONTEND_EXTS = frozenset({".tsx", ".jsx", ".vue", ".css", ".scss", ".less"})
#: 仅对前端/样式有意义的三个事实。后端项目里它们恒 False，
#: 会把 `facts_complete` 永久钉在 False、C 档永远不可达（2026-11-05 修正）。
_FRONTEND_ONLY = frozenset({"token_defined", "has_data_testid", "has_state_styles"})


def _ext_of(path: str) -> str:
    last_seg = path.rsplit("/", 1)[-1]
    return ("." + last_seg.rsplit(".", 1)[-1]) if "." in last_seg else ""


def is_applicable(key: str, ext: str) -> bool:
    """该事实在该目标文件类型下是否有意义。"""
    return ext in _FRONTEND_EXTS or key not in _FRONTEND_ONLY


def is_evidence_complete(facts: Sequence[FactResult]) -> bool:
    """适用项全部通过才算取证完备（取代「七项全过」）。

    空集合返回 False：没有事实就没有证据，不能算完备。
    """
    applicable = [fact for fact in facts if fact.applicable]
    return bool(applicable) and all(fact.passed for fact in applicable)


def _ev(raw: str) -> str:
    raw = raw.strip().replace("\n", " ⏎ ")
    return raw[:_EVIDENCE_LIMIT] if raw else "未找到"


def _rg_cwd(root: str) -> str | None:
    """rg 必须从**项目根**起搜。

    进程 cwd 是本工具自身仓库，而 `--glob` 用的是目标项目的相对路径——不传 cwd 时
    永远匹配不到，七项取证会集体误判为「未找到」（真实用户实测的 5 项反问即由此而来）。
    """
    return None if root in (".", "") else root


async def verify_facts(
    location: CodeLocation,
    sentence: str,
    runner: CommandRunner,
    reader: FileReader,
    *,
    root: str = ".",
) -> list[FactResult]:
    """逐项验证七项事实（F-104 行为列）；每项独立验证，互不短路。

    root：目标项目根（FileReader 文件系统访问需拼绝对路径，rg 相对搜索不受影响）。
    """

    def _fs(rel: str) -> str:
        return posixpath.join(root, rel) if root not in (".", "") else rel

    path, name = location.path, location.symbol_name
    ext = _ext_of(path)

    def applicable(key: str) -> bool:
        return is_applicable(key, ext)

    results: list[FactResult] = []

    # 1) 目标文件存在（文件系统检查经 FileReader）
    exists = await reader.exists(_fs(path))
    results.append(
        FactResult(
            "target_file_exists",
            exists,
            f"file={path}" if exists else f"missing={path}",
            applicable("target_file_exists"),
        )
    )

    # 2) 目标组件在文件中存在（rg 固定串搜索该文件）
    out = await runner.run(
        ["rg", "--fixed-strings", "-n", name, "--glob", path, ".", f"--route-key=symbol:{path}"],
        allowed_exit_codes=_RG_ALLOWED,
        cwd=_rg_cwd(root),
    )
    sym_hit = next((line for line in out.splitlines() if name in line), "")
    results.append(
        FactResult("symbol_in_file", bool(sym_hit), _ev(sym_hit), applicable("symbol_in_file"))
    )

    # 3) 样式 token 已定义（全局搜 token 名的定义处，限定样式文件）
    token = location.tokens[0] if location.tokens else ""
    tok_out = (
        await runner.run(
            [
                "rg",
                "--fixed-strings",
                "-n",
                # token 形如 --color-primary-500，直接当位置参数会被 rg 当成命令行选项
                # （实测 rg: unrecognized flag），必须用 -e 显式声明「这是模式」
                "-e",
                token,
                "--glob",
                "*.css",
                ".",
                f"--route-key=tokdef:{token}",
            ],
            allowed_exit_codes=_RG_ALLOWED,
            cwd=_rg_cwd(root),
        )
        if token
        else ""
    )
    tok_hit = next((line for line in tok_out.splitlines() if token and token in line), "")
    results.append(
        FactResult("token_defined", bool(tok_hit), _ev(tok_hit), applicable("token_defined"))
    )

    # 4) 组件含 data-testid（该文件内）
    out = await runner.run(
        ["rg", "-n", "data-testid", "--glob", path, ".", f"--route-key=testid:{path}"],
        allowed_exit_codes=_RG_ALLOWED,
        cwd=_rg_cwd(root),
    )
    tid = next((line for line in out.splitlines() if "data-testid" in line), "")
    results.append(
        FactResult("has_data_testid", bool(tid), _ev(tid), applicable("has_data_testid"))
    )

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
        cwd=_rg_cwd(root),
    )
    st = next(
        (
            line
            for line in out.splitlines()
            if any(s in line for s in (":hover", ":focus", ":active"))
        ),
        "",
    )
    results.append(
        FactResult("has_state_styles", bool(st), _ev(st), applicable("has_state_styles"))
    )

    # 6) 文件类型匹配预期（后缀在已知前端/样式后缀集内）
    results.append(
        FactResult(
            "file_type_matches",
            ext in _KNOWN_EXTS,
            f"ext={ext or 'none'}",
            applicable("file_type_matches"),
        )
    )

    # 7) 关联测试文件存在（F-103 已定位的 test_paths 逐一存在性检查）
    test_evidence = "未找到"
    test_ok = False
    for tp in location.test_paths:
        if await reader.exists(_fs(tp)):
            test_ok, test_evidence = True, f"test={tp}"
            break
    results.append(
        FactResult("test_file_exists", test_ok, test_evidence, applicable("test_file_exists"))
    )

    return results
