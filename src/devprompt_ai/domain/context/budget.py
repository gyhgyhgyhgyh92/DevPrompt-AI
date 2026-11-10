"""三层预算（纯计算，零 I/O）：轮次 / 单轮 token / 请求窗口。

- 轮次预算决定一个 turn 最多走几步（服务层已用 AgentBudget）；
- 单轮 token 预算按进程内存压力分档，防止工具输出把上下文撑爆；
- 请求级预算保证「输入 + 输出预留 + 安全边际」不超过模型窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: 单轮 token 上限分档（RSS 比例）；0 表示禁用本轮预算（内存已危急）。
_TURN_TOKEN_BY_RSS: Final[tuple[tuple[float, int], ...]] = (
    (0.7, 50_000),
    (0.85, 25_000),
)

#: 输出预留的硬上限（避免 max_tokens 配成离谱值把输入挤没）。
_MAX_OUTPUT_RESERVE: Final[int] = 256_000

#: 上下文装配预算随窗口缩放的比例与上限（2026-11-10）。
#: 300K→30K、600K→60K、1M→100K、2M→160K；小窗口由 floor 兜底。
STATE_BUDGET_RATIO: Final[float] = 0.10
STATE_BUDGET_CAP: Final[int] = 160_000
STATE_BUDGET_FLOOR: Final[int] = 30_000


def state_budget_for_window(window: int, *, floor: int = STATE_BUDGET_FLOOR) -> int:
    """按窗口档位计算上下文装配总预算。

    窗口越大，保留的历史越多，token 消耗随之上升；上限 160K 控制成本。
    窗口 ≤0 或未登记时返回 floor。
    """
    if window <= 0:
        return floor
    # 按 10K 向下取整，避免 1,048,576 × 10% = 104,857.6 这类非整千值；
    # 结果仍随档位单调：300K→30K、600K→60K、1M→100K、2M→200K（再封顶 160K）。
    scaled = int(window * STATE_BUDGET_RATIO) // 10_000 * 10_000
    return max(floor, min(scaled, STATE_BUDGET_CAP))


#: 上下文块级配额（字符）：超出即截断，防止单块吃光整窗。
DEFAULT_BLOCK_QUOTAS: Final[dict[str, int]] = {
    "project_instructions": 8_000,
    "project_memory": 3_000,
    "knowledge_manifest": 2_200,
    "seed_capsule": 3_000,
    "codebase_index": 4_000,
    "working_set": 6_000,
}


@dataclass(frozen=True, slots=True)
class RequestBudget:
    """请求级窗口预算。"""

    window: int
    max_output: int
    safety_margin: int

    @property
    def output_reserve(self) -> int:
        half = max(0, self.window // 2)
        return min(max(0, self.max_output), _MAX_OUTPUT_RESERVE, half)

    @property
    def input_budget(self) -> int:
        return max(0, self.window - self.output_reserve - self.safety_margin)

    def ratio(self, estimated_tokens: int) -> float:
        return estimated_tokens / self.input_budget if self.input_budget > 0 else 1.0

    def fits(self, estimated_tokens: int) -> bool:
        return estimated_tokens <= self.input_budget


def turn_token_budget(rss_ratio: float) -> int:
    """按内存压力返回单轮 token 上限；0 表示不截断（预算禁用）。"""
    for threshold, budget in _TURN_TOKEN_BY_RSS:
        if rss_ratio < threshold:
            return budget
    return 0


def request_budget(window: int, max_output: int) -> RequestBudget:
    """安全边际取「窗口的 10%」并封顶 16K；小窗口至少留 5%。"""
    margin = min(16_384, max(int(window * 0.10), int(window * 0.05)))
    return RequestBudget(window=window, max_output=max_output, safety_margin=margin)


class RequestBudgetError(ValueError):
    """请求级预算不足：调用方应先压缩再重发（A8）。"""


def ensure_request_fits(estimated_tokens: int, budget: RequestBudget, *, extra: int = 0) -> None:
    """LLM 调用前的硬断言；超出即抛，由外层走「压一次→重发」。"""
    total = max(0, estimated_tokens) + max(0, extra)
    if total > budget.input_budget:
        raise RequestBudgetError(f"request budget exceeded: {total} > {budget.input_budget}")


def fit_blocks(blocks: dict[str, str], quotas: dict[str, int] | None = None) -> dict[str, str]:
    """按块级配额截断；未登记配额的块原样保留。"""
    limits = quotas if quotas is not None else DEFAULT_BLOCK_QUOTAS
    fitted: dict[str, str] = {}
    for name, text in blocks.items():
        limit = limits.get(name)
        fitted[name] = text if limit is None or len(text) <= limit else text[: limit - 1] + "…"
    return fitted
