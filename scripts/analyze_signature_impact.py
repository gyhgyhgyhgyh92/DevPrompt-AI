"""候选带签名的排序收益上界分析（2026-11-05，零 LLM 调用）。

W3 排序实测需供应商额度，2026-11-05 因 402 余额耗尽两次中止。本脚本改用**离线归因**：
拿已有排序实测报告的 per-case 明细回答「签名最多能挽回多少条」，不花额度。

三个口径（均为历史实测数据，不调模型）：
1. 排序天花板：``expected_in_candidates`` 为真的占比——目标没进候选集时排序再准也命中不了。
2. 可挽回上界：排错且 top1 与目标**同名不同路径**的 case（签名正好提供区分信息）。
3. 签名无能为力：排错且 top1 与目标根本不同名（错误主因不是候选歧义）。

用法：
    uv run python scripts/analyze_signature_impact.py
    uv run python scripts/analyze_signature_impact.py \
        --out eval/agent/report-signature-impact-2026-11-05.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

DEFAULT_REPORT: Final = "eval/recall/report-ranking-2026-10-11-real.json"


def _name_of(candidate: str) -> str:
    """``符号@路径`` → 符号名（同名歧义判定用）。"""
    return candidate.split("@", 1)[0]


def _load_cases(report_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for repo in payload.get("repos", []):
        if not isinstance(repo, dict):
            continue
        for case in repo.get("details", []):
            if isinstance(case, dict):
                cases.append(case)
    return cases


def _analyze(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    hits = sum(1 for case in cases if case.get("hit"))
    in_pool = sum(1 for case in cases if case.get("expected_in_candidates"))
    ambiguous = 0
    recoverable: list[str] = []
    hopeless: list[str] = []
    for case in cases:
        expected = str(case.get("expected", ""))
        top5 = [str(item) for item in case.get("top5", []) if isinstance(item, str)]
        top1 = str(case.get("order0", "") or "")
        same_name = [item for item in top5 if _name_of(item) == _name_of(expected)]
        if len(same_name) >= 2 or (
            top1 and _name_of(top1) == _name_of(expected) and top1 != expected
        ):
            ambiguous += 1
        if case.get("hit"):
            continue
        if top1 and _name_of(top1) == _name_of(expected) and top1 != expected:
            recoverable.append(str(case.get("id", "")))
        else:
            hopeless.append(str(case.get("id", "")))
    return {
        "total": total,
        "hits": hits,
        "in_pool": in_pool,
        "accuracy": round(hits / total, 4) if total else 0.0,
        "ceiling": round(in_pool / total, 4) if total else 0.0,
        "ambiguous": ambiguous,
        "ambiguous_rate": round(ambiguous / total, 4) if total else 0.0,
        "recoverable": recoverable,
        "hopeless": hopeless,
        "upper_accuracy": round((hits + len(recoverable)) / total, 4) if total else 0.0,
    }


def _render(result: dict[str, Any], source: str) -> str:
    lines = [
        "# 候选带签名的排序收益上界（离线归因，零 LLM 调用）",
        "",
        f"数据源：`{source}`（F-801 第二段唯一有效的排序实测）",
        "",
        "## 结论速览",
        "",
        "| 口径 | 值 | 含义 |",
        "| --- | --- | --- |",
        f"| 实测命中率 | {result['hits']}/{result['total']}"
        f" = {result['accuracy']:.1%} | 历史基线（2026-10-11） |",
        f"| 排序天花板 | {result['in_pool']}/{result['total']}"
        f" = {result['ceiling']:.1%} | 目标进入候选集的比例，排序侧无法突破 |",
        f"| 候选歧义率 | {result['ambiguous']}/{result['total']}"
        f" = {result['ambiguous_rate']:.1%} | top5 内存在同名候选（签名有判别力的范围） |",
        f"| 签名可挽回上界 | {len(result['recoverable'])} 条 | 排错且 top1 与目标同名不同路径 |",
        f"| 签名无能为力 | {len(result['hopeless'])} 条 | 排错且 top1 与目标不同名 |",
        f"| 挽回后命中率上界 | {result['upper_accuracy']:.1%}"
        " | 乐观假设：签名让模型在歧义 case 上一律改判 |",
        "",
        "## 怎么读这组数",
        "",
        "1. **排序侧的空间由召回决定，不由排序决定**："
        "目标没进候选集的 case，排序层怎么排都命中不了。",
        "2. **签名只在同名歧义处有判别力**："
        "其余错误里 top1 与目标根本不同名，签名提供不了判别信息。",
        "3. 于是「签名最多能挽回多少」是一个**有界且很小**的量，与供应商额度无关。",
        "",
        "## 对 W3 决策的影响",
        "",
        "- 签名改造**保留**：零额外 LLM 调用、零额外进程，W1 已证不损害召回（95/100 未退化）；"
        "回退成本同样为零（ctags 不吐 signature 字段即自动降级）。",
        "- 「签名是否提升排序准确率」在**没有额度时不再是待决项**：收益上界已被离线量化，"
        "其不确定性只影响上界内的几个百分点，不影响任何门禁"
        "（MUST-25 第二段自 2026-10-15 起是参考指标）。",
        "- 若将来有额度再跑 A/B（带/无签名各 100 例），判读标准沿用既有文档："
        "error 率相近（<5%）时命中率差值才可归因于签名本身。",
        "",
        "## 本方法的限制（必须一并读）",
        "",
        "1. 上界是**乐观**的：假设模型见到签名就一定改判，实际收益只会更低。",
        "2. 歧义判定基于 top5 明细，top5 之外的同名候选未覆盖 → 歧义率是下界。",
        "3. 归因基于**无签名**时期的排序结果，不能反推「加签名后模型会怎么排」——"
        "它给上限，不能替代实测。",
        "",
        "## 明细",
        "",
        f"- 可挽回 case（{len(result['recoverable'])} 条）："
        f"{', '.join(result['recoverable']) or '无'}",
        f"- 签名无能为力 case（{len(result['hopeless'])} 条）："
        f"{', '.join(result['hopeless']) or '无'}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="候选带签名的排序收益上界分析（离线，零 LLM 调用）"
    )
    parser.add_argument("--report", default=DEFAULT_REPORT, help="排序实测报告 JSON")
    parser.add_argument("--out", default="", help="报告输出路径（.md）；空则只打印")
    args = parser.parse_args()
    report_path = Path(str(args.report))
    if not report_path.exists():
        print(f"报告不存在：{report_path}")
        return 2
    cases = _load_cases(report_path)
    if not cases:
        print(f"报告内无 per-case 明细：{report_path}")
        return 2
    result = _analyze(cases)
    text = _render(result, str(args.report))
    print(text)
    out_path = str(args.out)
    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"报告已写入 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
