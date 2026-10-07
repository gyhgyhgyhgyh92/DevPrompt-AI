"""F-802 供应商能力冒烟：结构化输出/函数调用/并行工具调用/流式。

用法：uv run python scripts/smoke_provider.py（需 LLM_BASE_URL/LLM_MODEL；无 env 退出码 2）
判定：四项全 PASS → 0；任一 FAIL → 1（标记该供应商不支持，SHOULD-02）。
"""

from __future__ import annotations

import asyncio

from agents import Agent, Runner, function_tool
from openai import AsyncOpenAI
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.harness.llm import _ensure_client  # noqa: PLC2701 —— 冒烟脚本专用


class Probe(BaseModel):
    answer: int


@function_tool
def add(a: int, b: int) -> int:
    """两数相加。"""
    return a + b


@function_tool
def shout(text: str) -> str:
    """原样返回大写。"""
    return text.upper()


async def _check_structured() -> bool:
    out = await _structured_call("计算 2+3 只输出 JSON")
    return out.answer == 5


async def _structured_call(user: str) -> Probe:
    from agents import Agent as _Agent

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    agent = _Agent(name="smoke", instructions="只输出 JSON", output_type=Probe, model=cfg.llm_model)
    result = await Runner.run(agent, user, max_turns=1)
    return result.final_output  # type: ignore[no-any-return]


async def _check_tool_call() -> bool:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    agent = Agent(
        name="smoke-tool",
        instructions="必须使用 add 工具计算 2+3",
        tools=[add],
        model=cfg.llm_model,
    )
    result = await Runner.run(agent, "2+3=?", max_turns=3)
    return "5" in str(result.final_output)


async def _check_parallel_tools() -> bool:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    agent = Agent(
        name="smoke-para",
        instructions="同时用 add(1,2) 与 add(3,4)，再各自调用 shout 报告结果",
        tools=[add, shout],
        model=cfg.llm_model,
    )
    result = await Runner.run(agent, "执行", max_turns=6)
    text = str(result.final_output)
    return "3" in text and "7" in text


async def _check_streaming() -> bool:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    agent = Agent(name="smoke-stream", instructions="回复 OK", model=cfg.llm_model)
    from openai.types.responses import ResponseTextDeltaEvent

    # run_streamed 返回同步流对象（非协程禁 await），事件经 stream_events() 异步迭代
    streamed = Runner.run_streamed(agent, "回复 OK")
    deltas = 0
    async for event in streamed.stream_events():
        if isinstance(event, ResponseTextDeltaEvent):
            deltas += 1
    return deltas > 0


async def main_async() -> int:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    if not cfg.llm_base_url or not cfg.llm_model:
        print("SKIP: 需要 LLM_BASE_URL/LLM_MODEL")
        return 2
    _ensure_client(cfg)
    _ = AsyncOpenAI  # 显式依赖标记
    checks = [
        ("structured_output", _check_structured),
        ("tool_call", _check_tool_call),
        ("parallel_tools", _check_parallel_tools),
        ("streaming", _check_streaming),
    ]
    failed: list[str] = []
    for name, check in checks:
        try:
            ok = await check()
        except Exception as exc:  # noqa: BLE001 —— 冒烟需捕获供应商侧任意异常
            ok = False
            print(f"  detail: {exc!r}")
        print(f"{name}: {'PASS' if ok else 'FAIL'}")
        if not ok:
            failed.append(name)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
