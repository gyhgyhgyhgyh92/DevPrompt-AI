"""F-801 第二段排序准确率实测（W3 门禁；--dry 离线干跑，真实模式经 create_decider）。

用法：
  uv run --no-sync python scripts/measure_ranking.py --project-dir eval/repos/click --dry
  uv run --no-sync python scripts/measure_ranking.py --all --dry
  uv run --no-sync python scripts/measure_ranking.py --all --limit 10

复用 measure_recall.py 的仓库加载与标注解析模式
（manifest.json + <cases-root>/<repo_id>/cases.jsonl）。
测量链路：build_candidates（≤25，MUST-09）-> decider.rank_components(sentence, candidates)
-> 判定 output.order[0] 对应候选是否命中标注 expected
（匹配规则同 measure_recall：符号名与路径双等）。

报告：eval/recall/report-ranking-<日期>-<mode>.json（mode = dry | real），
含 per-repo/per-case 明细、汇总准确率与 "metric_source"（决策层为单一 LLM 实现，
恒标注 "LLM 排序准确率"）。

退出码：--dry 为链路验证（mock 决策层下准确率无意义），跑通即 0、不套用 80% 门禁；
真实模式按 W3 门禁判定，准确率 ≥80% 返回 0，否则 1（决策树见 MUST-25：甲/乙必择一）；
账户级 API 故障（402 余额耗尽/401 鉴权失败）快速中止返回 2，不写报告。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.decision.fallback import create_decider
from devprompt_ai.domain.decision.port import (
    DecisionPort,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.models import Candidate, FactResult
from devprompt_ai.domain.retrieval.candidates import build_candidates
from devprompt_ai.harness.process import LocalCommandRunner, SymbolTableProvider

PASS_LINE = 0.8  # MUST-25 第二段：排序准确率通过线 ≥80%（仅真实模式套用）

_MAX_ERROR_RATIO = 0.5
"""单例错误率上限：超过即判「上游服务故障」并中止、不写报告（防 502 风暴产出无效 0%“实测”）。"""

_FATAL_API_MARKERS = (
    "401",
    "402",
    "403",
    "451",
    "Insufficient Balance",
    "not available in your region",
)
"""账户级 API 故障特征（余额耗尽/鉴权失败/区域封锁）：不可重试，继续测量只会产出整批无效 MISS。"""

_FATAL_ERROR_TYPES = ("APIStatusError",)
"""账户级故障的错误类名特征：LLM 侧 APIStatusError（余额耗尽/鉴权失败/区域封锁）。"""


def _is_fatal_api_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return any(t in name for t in _FATAL_ERROR_TYPES) and any(
        m in str(exc) for m in _FATAL_API_MARKERS
    )


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
    expected_in_candidates: bool
    candidate_count: int
    order0: str | None
    top5: list[str]
    error: str | None = None  # 单例 LLM 异常（超时等）：诚实计 MISS 并留因，不击穿整仓


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
    def accuracy(self) -> float:
        return self.hits / len(self.results) if self.results else 0.0


class _DryMockDecider:
    """--dry 内联 mock 决策层：按候选原序返回（order=[0,1,2,...]），confidence=0.5。

    零外部调用（同 MUST-25 第一段的离线约束）；实现全三方法以满足 DecisionPort 结构类型。
    """

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.5)

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        return FactProbeOutput(judgments=[], overall_confidence=0.5)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        return ScorePromptsOutput(scores=[])


def _load_cases(repo_dir: Path) -> list[Case]:
    """标注解析：同 measure_recall（cases.jsonl 四字段 id/sentence/expected_*）。"""
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
    repo: dict[str, object],
    provider: SymbolTableProvider,
    cases_root: Path,
    decider: DecisionPort,
    limit: int | None,
) -> RepoResult:
    root = str(repo["path"])
    repo_id = str(repo["id"])
    table = await provider.get(root)
    symbols = table.symbols
    small = bool(repo.get("small", False)) or len(symbols) < 25
    cases = await asyncio.to_thread(_load_cases, cases_root / repo_id)
    if limit is not None:
        cases = cases[:limit]
    results: list[CaseResult] = []
    for case in cases:
        cand = build_candidates(case.sentence, symbols)
        cands = cand.candidates
        # expected 匹配规则沿用 measure_recall：符号名与路径双等
        expected_in_candidates = any(
            c.name == case.expected_symbol and c.path == case.expected_path for c in cands
        )
        hit = False
        order0: str | None = None
        error: str | None = None
        if cands:
            try:
                out = await decider.rank_components(case.sentence, cands)
                top = cands[out.order[0]]
                order0 = f"{top.name}@{top.path}"
                hit = top.name == case.expected_symbol and top.path == case.expected_path
            except Exception as exc:  # noqa: BLE001 - 单例失败计 MISS 并留因
                if _is_fatal_api_error(exc):
                    raise  # 账户级故障：继续跑只会产出整批无效 MISS，快速中止交由上层处置
                error = f"{type(exc).__name__}: {exc}"[:200]
        results.append(
            CaseResult(
                case_id=case.case_id,
                sentence=case.sentence,
                expected_symbol=case.expected_symbol,
                expected_path=case.expected_path,
                hit=hit,
                expected_in_candidates=expected_in_candidates,
                candidate_count=len(cands),
                order0=order0,
                top5=[f"{c.name}@{c.path}" for c in cands[:5]],
                error=error,
            )
        )
    return RepoResult(repo_id=repo_id, symbol_total=len(symbols), small_repo=small, results=results)


def _build_payload(
    repos: list[RepoResult], mode: str, limit: int | None, metric_source: str
) -> dict[str, object]:
    total_cases = sum(len(r.results) for r in repos)
    total_hits = sum(r.hits for r in repos)
    accuracy = total_hits / total_cases if total_cases else 0.0
    # dry 模式不套用门禁：passed=null（gate_applied=false 表明准确率不作为判定依据）
    return {
        "date": date.today().isoformat(),
        "mode": mode,
        "metric_source": metric_source,
        "gate_applied": mode != "dry",
        "limit": limit,
        "total_cases": total_cases,
        "total_hits": total_hits,
        "accuracy": accuracy,
        "passed": accuracy >= PASS_LINE if mode == "real" else None,
        "repos": [
            {
                "id": r.repo_id,
                "symbol_total": r.symbol_total,
                "small": r.small_repo,
                "hits": r.hits,
                "cases": len(r.results),
                "accuracy": r.accuracy,
                "details": [
                    {
                        "id": c.case_id,
                        "sentence": c.sentence,
                        "expected": f"{c.expected_symbol}@{c.expected_path}",
                        "hit": c.hit,
                        "expected_in_candidates": c.expected_in_candidates,
                        "candidate_count": c.candidate_count,
                        "order0": c.order0,
                        "top5": c.top5,
                        "error": c.error,
                    }
                    for c in r.results
                ],
            }
            for r in repos
        ],
    }


def _select_repos(
    manifest: dict[str, Any], project_dir: Path | None, all_repos: bool
) -> list[dict[str, object]]:
    repos: list[dict[str, object]] = list(manifest["repos"])
    if all_repos:
        return repos
    assert project_dir is not None  # argparse 互斥必选组保证
    resolved = project_dir.resolve()
    matched = [r for r in repos if Path(str(r["path"])).resolve() == resolved]
    if matched:
        return matched
    # manifest 未登记的目录：以目录名为 repo_id，标注沿用 <cases-root>/<id>/cases.jsonl
    return [{"id": resolved.name, "path": str(resolved), "mock": False}]


async def main_async(
    manifest_path: Path,
    out_dir: Path,
    cases_root: Path,
    project_dir: Path | None,
    all_repos: bool,
    dry: bool,
    limit: int | None,
) -> int:
    raw = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
    manifest: dict[str, object] = json.loads(raw)
    repos = _select_repos(manifest, project_dir, all_repos)
    provider = SymbolTableProvider(LocalCommandRunner())
    decider: DecisionPort
    if dry:
        decider = _DryMockDecider()
        mode, metric_source = "dry", "dry"
    else:
        cfg = AppConfig()
        decider = create_decider(cfg)  # 决策层为单一 LLM 实现（2026-10-15）
        mode = "real"
        metric_source = "LLM 排序准确率"

    try:
        results = [await measure_repo(r, provider, cases_root, decider, limit) for r in repos]
    except Exception as exc:  # noqa: BLE001 - 快速失败路径：账户级故障给出可操作信息
        if _is_fatal_api_error(exc):
            print(f"[abort] 账户级 API 故障，测量中止：{type(exc).__name__}: {str(exc)[:200]}")
            print(
                "请修复供应商账户（充值/鉴权）或网络接入（区域封锁）后重跑"
                "（本次不写报告，避免无效结果污染门禁判定）。"
            )
            return 2
        raise
    total_cases = sum(len(r.results) for r in results)
    total_hits = sum(r.hits for r in results)
    accuracy = total_hits / total_cases if total_cases else 0.0
    error_cases = sum(1 for r in results for c in r.results if c.error is not None)
    if total_cases and error_cases / total_cases > _MAX_ERROR_RATIO:
        print(
            f"[abort] 单例错误率 {error_cases}/{total_cases} 超过 {_MAX_ERROR_RATIO:.0%}："
            "疑似上游服务故障、指标不可信；不写报告（避免无效结果污染门禁判定）。"
        )
        print("请稍后重试或修复上游后重跑。")
        return 2
    payload = _build_payload(results, mode, limit, metric_source)

    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    report = out_dir / f"report-ranking-{date.today().isoformat()}-{mode}.json"
    await asyncio.to_thread(
        report.write_text, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if dry:
        print(
            f"[dry] mock 排序 {total_hits}/{total_cases} = {accuracy:.1%}"
            "（链路验证，不套用门禁；mode=dry）"
        )
        print(f"报告：{report}")
        return 0
    passed = accuracy >= PASS_LINE
    status = "通过" if passed else "未通过"
    print(
        f"{metric_source} {total_hits}/{total_cases} = {accuracy:.1%}"
        f"（{status}；门禁 ≥80%；metric_source={metric_source}）"
    )
    print(f"报告：{report}")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="F-801 第二段排序准确率实测（W3 门禁）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project-dir", help="单仓目录（manifest 登记的 path 或任意含符号的目录）")
    group.add_argument("--all", action="store_true", help="manifest 全部仓库（默认 5 仓）")
    parser.add_argument(
        "--dry", action="store_true", help="干跑：内联 mock 决策层（原序返回），不调任何 LLM"
    )
    parser.add_argument("--limit", type=int, default=None, help="每仓最多取前 N 条用例")
    parser.add_argument("--manifest", default="eval/recall/manifest.json")
    parser.add_argument("--out", default="eval/recall")
    parser.add_argument("--cases-root", default="eval/recall")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须为正整数")
    return asyncio.run(
        main_async(
            Path(args.manifest),
            Path(args.out),
            Path(args.cases_root),
            Path(args.project_dir) if args.project_dir else None,
            args.all,
            args.dry,
            args.limit,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
