"""真实 LLM 最小流：真起服务 + 真实供应商跑完整 optimize。

默认跳过（不烧额度）。启用：
    $env:OBS_E2E_REAL_LLM=1; pytest tests/e2e/service/test_live_real_llm.py -m real_llm
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest

from conftest import envelope

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.environ.get("OBS_E2E_REAL_LLM") != "1",
        reason="真实 LLM 用例默认跳过；设 OBS_E2E_REAL_LLM=1 启用",
    ),
]

#: ASKING / CONFIRMING 是「等用户」的合法暂停态：真实模型经常先反问，不能算失败。
PAUSED_STATES = {"ASKING", "CONFIRMING"}
TERMINAL_STATES = {"DONE", "ABORTED"} | PAUSED_STATES
FLOW_TIMEOUT_S = 180.0
LONG_CALL_TIMEOUT_S = 240.0


def _wait_state(
    api: Any, session_id: str, targets: set[str], timeout: float = FLOW_TIMEOUT_S
) -> str:
    deadline = time.time() + timeout
    last_state = ""
    while time.time() < deadline:
        response = api.get("/api/v1/history", params={"limit": 50})
        body = envelope(response)
        for item in body["data"]["items"]:
            if item.get("session_id") == session_id:
                last_state = str(item.get("state", ""))
                if last_state in targets:
                    return last_state
                break
        time.sleep(2.0)
    raise AssertionError(f"流程 {timeout}s 未到目标状态 {targets}，最后：{last_state}")


def _snapshot(api: Any, session_id: str) -> dict[str, Any]:
    body = envelope(api.get(f"/api/v1/result/{session_id}"))
    assert body["code"] == 0, body
    return body["data"]


def _assert_trace_recorded(api: Any, session_id: str) -> None:
    body = envelope(api.get(f"/api/v1/obs/trace/sessions/{session_id}/traces"))
    assert body["code"] == 0
    assert body["data"]["items"], "真实流程没有任何 Trace 记录"


def test_real_llm_optimize_flow(api, tiny_project) -> None:  # type: ignore[no-untyped-def]
    """最小流：启动 → 到达暂停或终态 → Trace 落库。"""
    session_id = uuid.uuid4().hex
    response = api.post(
        "/api/v1/runs",
        json={
            "session_id": session_id,
            "project": str(tiny_project),
            "sentence": "把 submit_button 的返回值改成 new",
            "domain": "code",
        },
    )
    body = envelope(response)
    assert body["code"] == 0, body
    assert response.status_code == 202

    state = _wait_state(api, session_id, TERMINAL_STATES)
    assert state in TERMINAL_STATES
    _assert_trace_recorded(api, session_id)


def test_real_llm_query_rewrite_semantics() -> None:
    """轻量真实 LLM：同一目标微调要沿用，换页面要切换（各一次调用）。"""
    import asyncio

    from devprompt_ai.config import AppConfig
    from devprompt_ai.decision.fallback import LLMFallbackDecider

    decider = LLMFallbackDecider(AppConfig())

    async def _both() -> tuple[Any, Any]:
        # 同一事件循环内跑完：客户端池按 loop 绑定，跨 asyncio.run 会拿到已关闭的连接。
        return (
            await decider.rewrite_query("把 submit_button 的返回值改成 new", "submit_button"),
            await decider.rewrite_query("改成另一个页面的表格", "submit_button"),
        )

    same, switched = asyncio.run(_both())
    assert same.target.strip().lower() == "submit_button"
    assert same.confidence > 0
    assert switched.target.strip(), "改写结果必须给出目标"
    assert switched.target.strip().lower() != "submit_button"


def test_real_llm_followup_to_delivery(api, tiny_project) -> None:  # type: ignore[no-untyped-def]
    """完整链路：反问/护栏 → 答复或逃生 → 生成 → 交付（DONE + 方案）。"""
    session_id = uuid.uuid4().hex
    body = envelope(
        api.post(
            "/api/v1/runs",
            json={
                "session_id": session_id,
                "project": str(tiny_project),
                "sentence": "把 submit_button 的返回值改成 new",
                "domain": "code",
            },
        )
    )
    assert body["code"] == 0, body

    state = _wait_state(api, session_id, TERMINAL_STATES)
    rounds = 0
    while state in PAUSED_STATES and rounds < 3:
        snapshot = _snapshot(api, session_id)
        if state == "CONFIRMING":
            payload: dict[str, Any] = {"guardrail_action": "generate"}
        else:
            answers = {
                str(item["key"]): "按你的推荐处理"
                for item in snapshot.get("questions") or []
                if item.get("key")
            }
            # 没有问题键时（手工指定目标等）用逃生直接生成，避免卡死。
            payload = {"answers": answers} if answers else {"escape": True}
        replied = api.post(
            f"/api/v1/followup/{session_id}", json=payload, timeout=LONG_CALL_TIMEOUT_S
        )
        assert envelope(replied)["code"] == 0
        rounds += 1
        state = _wait_state(api, session_id, TERMINAL_STATES)

    assert state == "DONE", f"答复 {rounds} 轮后仍未交付：{state}"

    snapshot = _snapshot(api, session_id)
    assert snapshot["state"] == "DONE"
    assert snapshot.get("variant") is not None, "交付态没有方案正文"
    _assert_trace_recorded(api, session_id)
