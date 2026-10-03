"""F-801 第一段召回率实测（离线，不调任何外部 API）。

用法：uv run python scripts/measure_recall.py [--manifest ...] [--out ...] [--cases-root ...]
输出：report-<日期>.json（机器可读）+ report-<日期>.md（人读报告）

测量链路注记（脚本层补偿，src 修复后应移除）：
1. 本机 ctags 6.1.0 的 TypeScript 解析器仅映射 *.ts，.tsx 判为 NONE（零 tag）——
   EvalCommandRunner 为 ctags 调用追加 --map-TypeScript=+.tsx 补偿；
   src 的 build_ctags_args 缺该映射（F-101 实现缺陷，React/TSX 为主场景，待修复）。
2. ctags 输出路径相对 cwd（含仓库根前缀），而 Symbol 契约要求仓库相对路径——
   _repo_relative_symbols 剥离根前缀归一；SymbolTableProvider 未做该归一（待修复）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.candidates import build_candidates
from devprompt_ai.domain.retrieval.ports import CommandRunner
from devprompt_ai.harness.process import LocalCommandRunner, SymbolTableProvider

_TSX_MAP = "--map-TypeScript=+.tsx"  # 见模块 docstring 注记 1


class EvalCommandRunner:
    """CommandRunner 装饰器：为 ctags 调用追加 .tsx 语言映射（注记 1）。"""

    def __init__(self, inner: CommandRunner) -> None:
        self._inner = inner

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        if args and args[0] == "ctags":
            args = [args[0], _TSX_MAP, *args[1:]]
        return await self._inner.run(
            args, timeout=timeout, allowed_exit_codes=allowed_exit_codes, cwd=cwd
        )


def _repo_relative_symbols(symbols: list[Symbol], root: str) -> list[Symbol]:
    """将符号路径归一为仓库相对路径（注记 2）：剥离 ctags 输出中的仓库根前缀。"""
    prefix = root.replace("\\", "/").rstrip("/") + "/"
    out: list[Symbol] = []
    for s in symbols:
        path = s.path[len(prefix) :] if s.path.startswith(prefix) else s.path
        out.append(Symbol(name=s.name, path=path, line=s.line, kind=s.kind))
    return out


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    sentence: str
    expected_symbol: str
    expected_path: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    sentence: str
    expected_symbol: str
    expected_path: str
    hit: bool
    candidate_count: int
    matched_rank: int | None
    top5: list[str]


@dataclass(frozen=True, slots=True)
class RepoResult:
    repo_id: str
    symbol_total: int
    small_repo: bool
    results: list[CaseResult]

    @property
    def hits(self) -> int:
        return sum(1 for r in self.results if r.hit)

    @property
    def recall(self) -> float:
        return self.hits / len(self.results) if self.results else 0.0


def _load_cases(repo_dir: Path) -> list[Case]:
    cases: list[Case] = []
    with open(repo_dir / "cases.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cases.append(
                Case(obj["id"], obj["sentence"], obj["expected_symbol"], obj["expected_path"])
            )
    return cases


async def measure_repo(
    repo: dict[str, object], provider: SymbolTableProvider, cases_root: Path
) -> RepoResult:
    root = str(repo["path"])
    repo_id = str(repo["id"])
    table = await provider.get(root)
    symbols = _repo_relative_symbols(table.symbols, root)
    small = bool(repo.get("small", False)) or len(symbols) < 25
    cases = await asyncio.to_thread(_load_cases, cases_root / repo_id)
    results: list[CaseResult] = []
    for case in cases:
        cand = build_candidates(case.sentence, symbols)
        hit_rank: int | None = None
        for i, c in enumerate(cand.candidates):
            if c.name == case.expected_symbol and c.path == case.expected_path:
                hit_rank = i
                break
        results.append(
            CaseResult(
                case_id=case.case_id,
                sentence=case.sentence,
                expected_symbol=case.expected_symbol,
                expected_path=case.expected_path,
                hit=hit_rank is not None,
                candidate_count=len(cand.candidates),
                matched_rank=hit_rank,
                top5=[f"{c.name}@{c.path}" for c in cand.candidates[:5]],
            )
        )
    return RepoResult(repo_id=repo_id, symbol_total=len(symbols), small_repo=small, results=results)


def _report_md(repos: list[RepoResult], out: Path, corpus: str) -> Path:
    total_cases = sum(len(r.results) for r in repos)
    total_hits = sum(r.hits for r in repos)
    lines = [
        "# F-801 第一段 · 候选集召回率实测报告",
        "",
        f"- 日期：{date.today().isoformat()}　仓库数：{len(repos)}　样本数：{total_cases}",
        (
            f"- **总召回率：{total_hits}/{total_cases} = {total_hits / total_cases:.1%}**"
            "（通过线 ≥80%）"
        ),
        "",
    ]
    if corpus == "mock":
        lines += [
            "## ⚠️ 语料声明（mock 占位）",
            "",
            (
                "> **本报告基于 eval/recall 的 mock 占位语料（5 合成仓库），"
                "仅证明测量链路与报告渲染正确；不作为 MUST-25 生死线判定依据；"
                "生死线判定待真实仓库语料接入后重测（README 标注规范）。**"
            ),
            "",
        ]
    lines += [
        "测量链路注记：本脚本为 ctags 追加 `--map-TypeScript=+.tsx` 并将符号路径归一为仓库相对路径",
        (
            "（src 的 `build_ctags_args` 缺 tsx 映射、`SymbolTableProvider` 未做根前缀归一，"
            "待主流程修复后移除本补偿）。"
        ),
        "",
        "| 仓库 | 符号总数 | <25 标注 | 命中 | 召回率 |",
        "|---|---|---|---|---|",
    ]
    for r in repos:
        flag = "⚠️ 是" if r.small_repo else "否"
        hits = f"{r.hits}/{len(r.results)}"
        lines.append(f"| {r.repo_id} | {r.symbol_total} | {flag} | {hits} | {r.recall:.1%} |")
    small_repos = [r for r in repos if r.small_repo]
    if small_repos:
        lines += ["", "## 小仓库警告", ""]
        small_hits = sum(x.hits for x in small_repos)
        small_cases = sum(len(x.results) for x in small_repos)
        for r in small_repos:
            lines.append(
                f"- {r.repo_id}（{r.symbol_total} 符号）：召回率虚高，"
                f"小仓合计单独统计为 {small_hits}/{small_cases}"
            )
    misses = [(r, c) for r in repos for c in r.results if not c.hit]
    if misses:
        lines += ["", "## 失败案例（逐条）", ""]
        for r, c in misses[:20]:
            lines.append(f"- [{r.repo_id}/{c.case_id}] 原句：{c.sentence}")
            lines.append(
                f"  - 期望：{c.expected_symbol}@{c.expected_path} 未入候选；"
                f"top5：{'; '.join(c.top5)}"
            )
    passed = total_hits / total_cases >= 0.8
    verdict = (
        "✅ 达标，可进入阶段四"
        if passed
        else (
            "⛔ 未达标：检索层必须重做（放宽匹配 / 加入相似度排序 / 分层召回），"
            "不得进入阶段四（MUST-25）"
        )
    )
    lines += ["", "## 结论", "", f"- {verdict}"]
    report = out / f"report-{date.today().isoformat()}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _write_report_files(
    payload: dict[str, object], repos: list[RepoResult], out_dir: Path, corpus: str
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"report-{date.today().isoformat()}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _report_md(repos, out_dir, corpus)


async def main_async(manifest_path: Path, out_dir: Path, cases_root: Path) -> int:
    raw = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
    manifest = json.loads(raw)
    provider = SymbolTableProvider(EvalCommandRunner(LocalCommandRunner()))
    repos: list[RepoResult] = []
    for repo in manifest["repos"]:
        repos.append(await measure_repo(repo, provider, cases_root))
    total_cases = sum(len(r.results) for r in repos)
    total_hits = sum(r.hits for r in repos)
    recall = total_hits / total_cases if total_cases else 0.0
    corpus = "mock" if all(bool(r.get("mock", False)) for r in manifest["repos"]) else "real"

    payload: dict[str, object] = {
        "date": date.today().isoformat(),
        "corpus": corpus,
        "recall": recall,
        "passed": recall >= 0.8,
        "repos": [
            {
                "id": r.repo_id,
                "symbol_total": r.symbol_total,
                "small": r.small_repo,
                "hits": r.hits,
                "cases": len(r.results),
                "details": [
                    {
                        "id": c.case_id,
                        "hit": c.hit,
                        "rank": c.matched_rank,
                        "sentence": c.sentence,
                        "top5": c.top5,
                    }
                    for c in r.results
                ],
            }
            for r in repos
        ],
    }
    md_path = await asyncio.to_thread(_write_report_files, payload, repos, out_dir, corpus)
    status = "通过" if payload["passed"] else "未通过"
    print(f"召回率 {total_hits}/{total_cases} = {recall:.1%}（{status}；corpus={corpus}）")
    print(f"报告：{md_path}")
    return 0 if payload["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="F-801 第一段召回率实测（离线）")
    parser.add_argument("--manifest", default="eval/recall/manifest.json")
    parser.add_argument("--out", default="eval/recall")
    parser.add_argument("--cases-root", default="eval/recall")
    args = parser.parse_args()
    return asyncio.run(main_async(Path(args.manifest), Path(args.out), Path(args.cases_root)))


if __name__ == "__main__":
    raise SystemExit(main())
