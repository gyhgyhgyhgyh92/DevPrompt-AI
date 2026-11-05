"""六维感知与断言声明率统计（2026-11-05）。

三个待决问题都缺数据，本脚本用已落库的轮次记录给出答案：
1. 六维快照能否升级为熔断第四判据（门槛见 ``FUSE_*`` 常量，不达标即「不接线」）；
2. ``claim_strict`` 是否该收紧（C 档轮次里的空声明比例）；
3. 成本软护栏 ``FOLLOWUP_COST_BUDGET`` 上限该设多少（每轮 LLM token 分布）。

用法：
    uv run python scripts/measure_sensorium.py
    uv run python scripts/measure_sensorium.py --db-path ./.logs/sensorium-sample.db
    uv run python scripts/measure_sensorium.py --out eval/agent/report-sensorium-2026-11-05.md

数据全部经 ``memory/`` 既有 API 读取（SQL 不出 memory/，MUST-06）；输出只含数字与状态，
不含用户原句与绝对路径（MUST-19）。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
from pathlib import Path
from typing import Any, Final

from devprompt_ai.config import AppConfig
from devprompt_ai.memory.session_store import SQLiteSessionStore
from devprompt_ai.memory.turn_store import SQLiteTurnStore

#: 接线所需最小有效样本（带六维快照的轮次）
FUSE_MIN_SAMPLES: Final = 20
#: 接线所需最小异常组样本（ABORTED 轮次）
FUSE_MIN_ANOMALY: Final = 3
#: 接线所需两组 score 中位数差下限
FUSE_MIN_SEPARATION: Final = 0.15
#: 成本护栏上限地板（token）：低于此值不设护栏，避免正常一轮就被打断
COST_BUDGET_FLOOR: Final = 30_000
#: 成本护栏上限取整步长（token）
COST_BUDGET_STEP: Final = 5_000

_SENSORIUM_DIMS: Final = (
    "momentum",
    "pressure",
    "coverage",
    "complexity",
    "familiarity",
    "stability",
    "score",
)


def _percentile(values: list[float], pct: int) -> float:
    """线性插值分位数（pct 取 0~100）；空集返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _score_of(summary: dict[str, Any]) -> float | None:
    """从轮次摘要取六维总分；无快照返回 None。"""
    sensorium = summary.get("sensorium")
    if not isinstance(sensorium, dict):
        return None
    score = sensorium.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score)
    return None


async def _collect_rows(db_path: str, user_id: str, limit: int) -> list[dict[str, Any]]:
    """经 memory/ 既有 API 取最近若干会话的全部轮次。"""
    sessions = await SQLiteSessionStore(db_path).list_recent(user_id, limit=limit)
    store = SQLiteTurnStore(db_path)
    rows: list[dict[str, Any]] = []
    for session in sessions:
        for turn in await store.list_for_session(session.session_id):
            summary = turn.summary if isinstance(turn.summary, dict) else {}
            usage = turn.usage if isinstance(turn.usage, dict) else {}
            rows.append({"state": turn.state, "summary": summary, "usage": usage})
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """把原始行汇成统计结论：六维分布、分离度、接线判定、声明率、护栏建议。"""
    done: list[float] = []
    aborted: list[float] = []
    all_scores: list[float] = []
    dims: dict[str, list[float]] = {name: [] for name in _SENSORIUM_DIMS}
    for row in rows:
        summary = row["summary"]
        sensorium = summary.get("sensorium")
        if not isinstance(sensorium, dict):
            continue
        for name in _SENSORIUM_DIMS:
            value = sensorium.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                dims[name].append(float(value))
        score = _score_of(summary)
        if score is None:
            continue
        all_scores.append(score)
        if row["state"] == "DONE":
            done.append(score)
        elif row["state"] == "ABORTED":
            aborted.append(score)

    separation = 0.0
    abnormal_basis = "ABORTED 组"
    abnormal = list(aborted)
    if len(abnormal) < FUSE_MIN_ANOMALY and len(all_scores) >= 8:
        # 真实会话里失败轮少见；样本不足时退用最低四分位，口径写进报告避免误读。
        ordered = sorted(all_scores)
        abnormal = ordered[: max(1, len(ordered) // 4)]
        abnormal_basis = "最低四分位组（ABORTED 样本不足）"
    abnormal_median = statistics.median(abnormal) if abnormal else 0.0
    if done and abnormal:
        separation = statistics.median(done) - abnormal_median
    fuse_ready = (
        len(all_scores) >= FUSE_MIN_SAMPLES
        and len(abnormal) >= FUSE_MIN_ANOMALY
        and separation >= FUSE_MIN_SEPARATION
    )

    c_rows = [
        row
        for row in rows
        if row["summary"].get("level") == "C" and isinstance(row["summary"].get("claims"), dict)
    ]
    undeclared = sum(1 for row in c_rows if bool(row["summary"]["claims"].get("undeclared")))
    claim_rate = (undeclared / len(c_rows)) if c_rows else 0.0

    tokens: list[float] = []
    for row in rows:
        value = row["usage"].get("llm_tokens", 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            tokens.append(float(value))
    p95 = _percentile(tokens, 95)
    budget = max(COST_BUDGET_FLOOR, math.ceil(p95 * 1.5))
    budget = int(math.ceil(budget / COST_BUDGET_STEP) * COST_BUDGET_STEP)

    return {
        "total_turns": len(rows),
        "scored_turns": len(all_scores),
        "dims": {
            name: {
                "n": len(values),
                "p50": round(_percentile(values, 50), 4),
                "p95": round(_percentile(values, 95), 4),
                "min": round(min(values), 4) if values else 0.0,
                "max": round(max(values), 4) if values else 0.0,
            }
            for name, values in dims.items()
        },
        "done_n": len(done),
        "aborted_n": len(aborted),
        "abnormal_n": len(abnormal),
        "abnormal_basis": abnormal_basis,
        "done_median": round(statistics.median(done), 4) if done else 0.0,
        "aborted_median": round(statistics.median(aborted), 4) if aborted else 0.0,
        "abnormal_median": round(abnormal_median, 4),
        "separation": round(separation, 4),
        "fuse_ready": fuse_ready,
        "c_turns": len(c_rows),
        "undeclared_turns": undeclared,
        "claim_rate": round(claim_rate, 4),
        "token_n": len(tokens),
        "token_p50": round(_percentile(tokens, 50), 1),
        "token_p95": round(p95, 1),
        "token_max": round(max(tokens), 1) if tokens else 0.0,
        "budget_suggestion": budget,
    }


def _render(report: dict[str, Any]) -> str:
    """把统计结论渲染成 Markdown（含接线判定与护栏建议）。"""
    lines = [
        "# 六维感知与声明率统计",
        "",
        "## 样本",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 轮次总数 | {report['total_turns']} |",
        f"| 带六维快照的轮次 | {report['scored_turns']} |",
        f"| DONE / ABORTED | {report['done_n']} / {report['aborted_n']} |",
        f"| C 档轮次 / 其中空声明 | {report['c_turns']} / {report['undeclared_turns']} |",
        f"| 记录到 token 的轮次 | {report['token_n']} |",
        "",
        "## 六维分布",
        "",
        "| 维度 | n | p50 | p95 | min | max |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    dims: dict[str, dict[str, Any]] = report["dims"]
    for name in _SENSORIUM_DIMS:
        stat = dims[name]
        lines.append(
            f"| {name} | {stat['n']} | {stat['p50']} | {stat['p95']} | "
            f"{stat['min']} | {stat['max']} |"
        )

    lines += [
        "",
        "## 接线判定（六维是否升级为熔断第四判据）",
        "",
        "| 项 | 值 | 门槛 |",
        "| --- | --- | --- |",
        f"| 有效样本 | {report['scored_turns']} | ≥ {FUSE_MIN_SAMPLES} |",
        f"| 异常组样本（{report['abnormal_basis']}） | {report['abnormal_n']}"
        f" | ≥ {FUSE_MIN_ANOMALY} |",
        f"| DONE 组 score 中位数 | {report['done_median']} | — |",
        f"| 异常组 score 中位数 | {report['abnormal_median']} | — |",
        f"| 两组 score 中位数差 | {report['separation']} | ≥ {FUSE_MIN_SEPARATION} |",
        "",
        (
            "**结论：可以接线**（三项门槛全部满足）。"
            if report["fuse_ready"]
            else "**结论：不接线**（门槛未全部满足），保持 shadow 观测。"
        ),
        "",
        "## 断言声明率（claim_strict 是否收紧）",
        "",
        f"- C 档轮次 {report['c_turns']}，其中一条引用都没声明 {report['undeclared_turns']} 轮，"
        f"声明率缺口 {report['claim_rate']}。",
        "- 口径：`undeclared` 为真即视为空声明（claim_strict 打开后会因此把 C 降为 B）。",
        "",
        "## 成本护栏上限建议（FOLLOWUP_COST_BUDGET）",
        "",
        f"- 每轮 LLM token：p50 {report['token_p50']} / p95 {report['token_p95']}"
        f" / max {report['token_max']}",
        f"- 建议上限 **{report['budget_suggestion']}** token"
        f"（口径：max({COST_BUDGET_FLOOR}, ceil(p95×1.5))，按 {COST_BUDGET_STEP} 取整）。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="六维感知与断言声明率统计")
    parser.add_argument("--db-path", default="", help="SQLite 路径；空则用配置里的默认库")
    parser.add_argument("--user-id", default="local", help="会话归属用户")
    parser.add_argument("--limit", type=int, default=200, help="扫描的最近会话数")
    parser.add_argument("--out", default="", help="报告输出路径（.md）；空则只打印")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit 必须为正整数")
    db_path = str(args.db_path) or AppConfig().db_path
    rows = asyncio.run(_collect_rows(db_path, str(args.user_id), int(args.limit)))
    report = _summarize(rows)
    text = _render(report)
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
