"""逐条核验 cases.jsonl 的 expected_symbol / expected_path 是否在真实仓库中成立。

判定维度（只针对标注质量，不涉及 HIT/MISS）：
  path_exists      : expected_path 文件是否存在
  symbol_in_file   : expected_symbol 是否定义/出现在该文件中
  symbol_in_repo   : expected_symbol 是否在仓库任意位置出现（防止 path 写错但符号存在）
  exported_public  : 符号是否可能是公开 API（axios/headlessui/pinia 需额外判断）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = ROOT / "eval" / "recall"
REPOS_ROOT = ROOT / "eval" / "repos"
REPO_IDS = ["click", "requests", "pinia", "axios", "headlessui"]


def load_cases(repo_id: str) -> list[dict]:
    p = CASES_ROOT / repo_id / "cases.jsonl"
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def path_exists(repo: Path, rel: str) -> bool:
    return (repo / rel).is_file()


def count_in_file(repo: Path, rel: str, symbol: str) -> int:
    f = repo / rel
    if not f.is_file():
        return 0
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    if not symbol:
        return 0
    # 词边界匹配，$patch / $reset 这类带 $ 的符号单独处理
    pattern = re.escape(symbol)
    if symbol.startswith("$"):
        pattern = re.escape(symbol)
    else:
        pattern = r"(?<![\w$])" + pattern + r"(?![\w$])"
    return len(re.findall(pattern, text))


def symbol_in_repo(repo: Path, symbol: str) -> tuple[bool, str, list[str]]:
    """返回 (是否存在, 首个命中文件相对路径, 全部命中文件列表)

    注意：git grep -E 不支持 lookbehind 断言，因此这里用 -F 固定串拿候选文件，
    再在 Python 侧做词边界过滤。
    """
    if not symbol:
        return False, "", []
    try:
        proc = subprocess.run(
            ["git", "grep", "-l", "-F", symbol, "--"],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:  # pragma: no cover
        return False, f"<git grep error: {exc}>", []
    files = [x for x in proc.stdout.splitlines() if x.strip()]
    if not files:
        return False, "", []

    if symbol.startswith("$"):
        pattern = re.compile(re.escape(symbol))
    else:
        pattern = re.compile(r"(?<![\w$])" + re.escape(symbol) + r"(?![\w$])")

    strict: list[str] = []
    for rel in files:
        f = repo / rel
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if pattern.search(text):
            strict.append(rel)
    # 固定串命中但词边界不通过 → 宽松视为存在
    hits = strict or files
    return True, hits[0], hits


# 定义式出现：符号是否在该文件中被"定义"，而不只是被引用。
# 这是判断 expected 是否为合理修改目标的关键 —— 符号若只被引用，
# 说明真正的修改点不在这个文件。
DEF_PATTERNS = [
    # Python
    r"^\s*(?:async\s+)?def\s+{s}\s*\(",
    r"^\s*class\s+{s}\b",
    r"^\s*{s}\s*[:=]",
    # JS / TS —— 允许泛型参数：function foo<T = any>( / function foo<T>(...
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+{s}\s*(?:<[^>]*>)?\s*\(",
    r"^\s*(?:export\s+)?(?:const|let|var)\s+{s}\s*(?::[^=]*)?=",
    r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+{s}\b",
    r"^\s*{s}\s*(?:<[^>]*>)?\s*\(",
    r"export\s+default\s+{s}\b",
    r"^\s*export\s*\{{[^}}]*\b{s}\b[^}}]*\}}",
    r"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var|function)\s+{s}\b",
    r"^\s*export\s+type\s+{s}\b",
    r"^\s*export\s+interface\s+{s}\b",
]


def is_defined_in_file(repo: Path, rel: str, symbol: str) -> bool:
    f = repo / rel
    if not f.is_file():
        return False
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    if symbol.startswith("$"):
        # $patch / $reset：store 实例属性，检查 $patch( / "$patch" 之类的成员定义
        pats = [rf"\b{symbol}\b\s*[:=(]", rf"['\"]{re.escape(symbol)}['\"]"]
    else:
        pats = [p.format(s=re.escape(symbol)) for p in DEF_PATTERNS]
    return any(re.search(p, text, re.MULTILINE) for p in pats)


def main() -> int:
    report: dict[str, dict] = {}
    for repo_id in REPO_IDS:
        repo = REPOS_ROOT / repo_id
        if not repo.is_dir():
            print(f"[SKIP] repo missing: {repo_id}")
            continue
        rows = []
        for case in load_cases(repo_id):
            sym = case["expected_symbol"]
            rel = case["expected_path"]
            pe = path_exists(repo, rel)
            n_file = count_in_file(repo, rel, sym)
            in_repo, first_hit, all_hits = symbol_in_repo(repo, sym)
            defined = is_defined_in_file(repo, rel, sym)
            rows.append(
                {
                    "id": case["id"],
                    "sentence": case["sentence"],
                    "expected_symbol": sym,
                    "expected_path": rel,
                    "path_exists": pe,
                    "symbol_in_file": n_file,
                    "symbol_in_repo": in_repo,
                    "defined_in_file": defined,
                    "repo_first_hit": first_hit,
                    "path_in_hitlist": rel in all_hits,
                    "hit_count": len(all_hits),
                }
            )
        report[repo_id] = rows

    out_path = CASES_ROOT / "label-audit-raw.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    for repo_id, rows in report.items():
        bad_path = [r["id"] for r in rows if not r["path_exists"]]
        bad_file = [r["id"] for r in rows if r["path_exists"] and r["symbol_in_file"] == 0]
        bad_repo = [r["id"] for r in rows if not r["symbol_in_repo"]]
        not_defined = [r["id"] for r in rows if not r["defined_in_file"]]
        not_in_hit = [r["id"] for r in rows if not r["path_in_hitlist"]]
        print(f"\n=== {repo_id} (n={len(rows)}) ===")
        print(f"path 不存在          : {bad_path}")
        print(f"文件内找不到符号    : {bad_file}")
        print(f"仓库内找不到符号    : {bad_repo}")
        print(f"expected_path 不在命中集: {not_in_hit}")
        print(f"文件内无定义式出现  : {not_defined}")
    print(f"\nraw -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
