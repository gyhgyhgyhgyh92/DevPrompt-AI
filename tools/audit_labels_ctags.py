"""按 README 标注规范，用项目自身 SymbolTableProvider（ctags）复核 100 条 expected。

规范原文：
  expected_symbol / expected_path 必须是该仓库真实存在且 ctags 可解析的符号
  （以 SymbolTableProvider.get 解析结果为准；标注了 ctags 抽不出的符号属假阴性，剔除并记录）

输出 eval/recall/label-audit-ctags.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from devprompt_ai.harness.process import LocalCommandRunner, SymbolTableProvider  # noqa: E402

CASES_ROOT = ROOT / "eval" / "recall"
REPO_IDS = ["click", "requests", "pinia", "axios", "headlessui"]


def load_cases(repo_id: str) -> list[dict]:
    p = CASES_ROOT / repo_id / "cases.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


async def main() -> int:
    provider = SymbolTableProvider(LocalCommandRunner())
    report: dict[str, dict] = {}

    for repo_id in REPO_IDS:
        root = f"eval/repos/{repo_id}"
        result = await provider.get(root)
        symbols = result.symbols
        # 建立 name -> [path] 索引
        by_name: dict[str, list[str]] = {}
        for sym in symbols:
            by_name.setdefault(sym.name, []).append(sym.path)

        rows = []
        for case in load_cases(repo_id):
            name = case["expected_symbol"]
            path = case["expected_path"]
            paths = by_name.get(name, [])
            rows.append(
                {
                    "id": case["id"],
                    "sentence": case["sentence"],
                    "expected_symbol": name,
                    "expected_path": path,
                    "ctags_found": name in by_name,
                    "ctags_paths": paths,
                    "path_match": path in paths,
                }
            )

        found = sum(1 for r in rows if r["ctags_found"])
        matched = sum(1 for r in rows if r["path_match"])
        report[repo_id] = {
            "symbol_total": len(symbols),
            "cases": rows,
            "ctags_found": found,
            "path_match": matched,
            "n": len(rows),
        }
        print(f"\n=== {repo_id} ===")
        print(f"ctags 符号总数: {len(symbols)}")
        print(f"expected 被 ctags 解析: {found}/{len(rows)}")
        print(f"且 path 完全匹配      : {matched}/{len(rows)}")
        miss = [r["id"] for r in rows if not r["ctags_found"]]
        pmiss = [r["id"] for r in rows if r["ctags_found"] and not r["path_match"]]
        if miss:
            print(f"ctags 抽不出 [{len(miss)}]: {miss}")
            for r in rows:
                if not r["ctags_found"]:
                    print(f"    {r['id']}  {r['expected_symbol']}  <- {r['expected_path']}")
        if pmiss:
            print(f"符号在但 path 不同 [{len(pmiss)}]: {pmiss}")
            for r in rows:
                if r["ctags_found"] and not r["path_match"]:
                    print(f"    {r['id']}  {r['expected_symbol']}")
                    print(f"        标注: {r['expected_path']}")
                    print(f"        实际: {r['ctags_paths']}")

    out = CASES_ROOT / "label-audit-ctags.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
