"""上下文档位与 token 承载量验证（2026-11-10）。

只做本地纯计算，不联网、不写文件：

1. 打印常见标称窗口的统一四档表；
2. 用固定长历史（2000 轮）分别以各档位的 state_budget 装配上下文；
3. 打印 history_block 的估算 token，并断言随档位单调不减。

运行：

    uv run python scripts/measure_context_tiers.py
    uv run python scripts/measure_context_tiers.py --json
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from devprompt_ai.domain.context import ContextBudget, TurnInput, TurnSummary, build_context
from devprompt_ai.domain.context.budget import state_budget_for_window
from devprompt_ai.domain.context.build_context import estimate_tokens
from devprompt_ai.domain.model_spec import window_tiers

#: 常见标称窗口（覆盖小窗口、1024 系与超过 1M 的模型）
WINDOWS = (131_072, 200_000, 272_000, 307_200, 500_000, 614_400, 1_048_576, 1_500_000, 2_000_000)

#: 用于验证 token 单调的档位（300K/600K/1M/2M）
MEASURE_TIERS = (307_200, 614_400, 1_048_576, 2_000_000)

_TURNS = tuple(
    TurnSummary(
        turn_id=f"t{index}",
        turn_index=index,
        target="Button",
        conclusion="复用主题令牌并覆盖五态",
        open_items=("对比度是否达标",),
        decision="B",
        rejected=("C 激进版",),
    )
    for index in range(2000)
)

_CURRENT = TurnInput(
    sentence="把提交按钮改成红色",
    facts=("token_defined=通过", "test_file_exists=通过"),
    clarifications={"scope": "只改这一处"},
    target="Button",
)


def _tier_table() -> list[dict[str, Any]]:
    return [
        {
            "window": window,
            "tiers": list(window_tiers(window)),
            "state_budgets": [state_budget_for_window(tier) for tier in window_tiers(window)],
        }
        for window in WINDOWS
    ]


def _measure() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tier in MEASURE_TIERS:
        budget = state_budget_for_window(tier)
        payload = build_context(
            _TURNS,
            _CURRENT,
            budget=ContextBudget(total=budget),
            context_window=tier,
            estimated_tokens=1_000,
        )
        rows.append(
            {
                "tier": tier,
                "state_budget": budget,
                "history_tokens": estimate_tokens(payload.history_block),
                "truncated_layers": list(payload.truncated_layers),
            }
        )
    sizes = [row["history_tokens"] for row in rows]
    if sizes != sorted(sizes) or sizes[-1] <= sizes[0]:
        raise SystemExit(f"token 未随档位单调增加：{rows}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="上下文档位与 token 承载量验证")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    report = {"tier_table": _tier_table(), "measurements": _measure()}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("== 统一四档表 ==")
    for row in report["tier_table"]:
        print(f"标称 {row['window']:>9} → 档位 {row['tiers']} → 预算 {row['state_budgets']}")
    print("\n== 长历史承载量（2000 轮） ==")
    for row in report["measurements"]:
        print(
            f"档位 {row['tier']:>9} | state_budget {row['state_budget']:>6} "
            f"| history_tokens {row['history_tokens']:>7} | truncated {row['truncated_layers']}"
        )
    print("\n结论：history_tokens 随档位单调不减 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
