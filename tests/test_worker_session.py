"""只读 worker 测试：提示契约、成功解析、超时与异常降级。"""

from __future__ import annotations

import asyncio

from devprompt_ai.domain.agent.work_order import WorkOrder
from devprompt_ai.harness.worker_session import build_worker_prompt, run_read_worker


def _order() -> WorkOrder:
    return WorkOrder(
        id="w1",
        parent_turn_id="t1",
        profile="code_scout",
        objective="查清导出按钮在哪",
        scope_files=("src/ui/Button.tsx",),
    )


def test_prompt_requires_json_and_no_writes() -> None:
    system, user = build_worker_prompt(_order())

    assert "只读" in system and "JSON" in system
    assert "src/ui/Button.tsx" in user
    assert "查清导出按钮在哪" in user


async def test_success_returns_verified() -> None:
    async def execute(_order: WorkOrder) -> str:
        return '{"summary": "在 Button.tsx 第 12 行", "evidence": ["src/ui/Button.tsx:12"]}'

    result = await run_read_worker(_order(), execute=execute)

    assert result.status == "ok"
    assert result.evidence_status == "verified"
    assert result.evidence == ("src/ui/Button.tsx:12",)


async def test_timeout_becomes_blocked() -> None:
    async def slow(_order: WorkOrder) -> str:
        await asyncio.sleep(5)
        return "{}"

    result = await run_read_worker(_order(), execute=slow, timeout_s=0.01)

    assert result.status == "blocked"
    assert result.evidence_status == "unverified"


async def test_exception_becomes_blocked() -> None:
    async def boom(_order: WorkOrder) -> str:
        raise RuntimeError("llm down")

    result = await run_read_worker(_order(), execute=boom)

    assert result.status == "blocked"
    assert "RuntimeError" in result.output


async def test_salvage_is_marked_unverified() -> None:
    async def garbled(_order: WorkOrder) -> str:
        return "这不是 JSON，但有关键信息"

    result = await run_read_worker(_order(), execute=garbled)

    assert result.status == "partial"
    assert result.salvaged is True
    assert result.evidence_status == "unverified"
