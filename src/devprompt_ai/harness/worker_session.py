"""只读 worker（K3）：在独立上下文里跑一个工单，只回传结论与证据。

本模块不自己调 LLM：执行函数由调用方注入（便于在测试里给定输出、在真实场景里接
`chat_structured`）。这样 worker 的**契约**（超时、打捞、未验证标记）可以独立测试。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from devprompt_ai.domain.agent.delegation import WorkerResult, parse_worker_output
from devprompt_ai.domain.agent.work_order import WorkOrder

#: 只读 worker 的默认预算：够读完关键文件，又不至于拖住主会话。
DEFAULT_WORKER_TIMEOUT_S: float = 60.0


def build_worker_prompt(order: WorkOrder) -> tuple[str, str]:
    """构造 worker 的系统/用户提示：要求只回 JSON，且证据必须是实测。"""
    system = (
        "你是只读探查 worker。只允许读取与检索，不得修改任何文件。\n"
        '输出必须是 JSON：{"summary": "一句话结论", "evidence": ["路径:行号"]}。\n'
        "证据未实测时不要编造，直接留空并在 summary 里说明。"
    )
    scope = "、".join(order.scope_files) if order.scope_files else "（未限定）"
    user = f"目标：{order.objective}\n范围：{scope}\n预算：{order.budget_ms}ms"
    return system, user


async def run_read_worker(
    order: WorkOrder,
    *,
    execute: Callable[[WorkOrder], Awaitable[str]],
    timeout_s: float = DEFAULT_WORKER_TIMEOUT_S,
    required_terms: Sequence[str] = (),
) -> WorkerResult:
    """执行只读工单；超时或异常一律降级为 blocked/partial，绝不抛出到主循环。"""
    try:
        raw = await asyncio.wait_for(execute(order), timeout=timeout_s)
    except TimeoutError:
        return WorkerResult("blocked", output="worker timeout", evidence_status="unverified")
    except Exception as exc:  # noqa: BLE001 - worker 失败不能拖垮主会话
        return WorkerResult(
            "blocked",
            output=f"worker error: {type(exc).__name__}",
            evidence_status="unverified",
        )
    return parse_worker_output(raw, required_terms=required_terms)
