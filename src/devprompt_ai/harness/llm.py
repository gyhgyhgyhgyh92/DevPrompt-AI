"""多供应商 LLM 封装（F-004）：OpenAI 兼容协议 + Chat Completions + 禁 tracing。

SDK 三约束（技术栈 §4.5）：set_default_openai_api("chat_completions")；
set_tracing_disabled(True)；base_url 经 set_default_openai_client 注入。
"""

from __future__ import annotations

import asyncio
from typing import TypeVar

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import ConfigurationError, GenerationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_client: AsyncOpenAI | None = None
_configured_model: str = ""


def _ensure_client(cfg: AppConfig) -> AsyncOpenAI:
    """惰性初始化并全局注册 OpenAI 兼容客户端（同一配置只注册一次）。"""
    global _client, _configured_model
    if not cfg.llm_base_url or not cfg.llm_model:
        raise ConfigurationError(
            "LLM 未配置：需要 LLM_BASE_URL / LLM_MODEL 环境变量",
            context={
                "llm_base_url_set": bool(cfg.llm_base_url),
                "llm_model_set": bool(cfg.llm_model),
            },
        )
    if _client is None or _configured_model != cfg.llm_model:
        _client = AsyncOpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key or "EMPTY")
        set_default_openai_client(_client)
        set_default_openai_api("chat_completions")  # 第三方基本不支持 Responses API
        set_tracing_disabled(True)  # 第三方 key 走 tracing 会 401
        _configured_model = cfg.llm_model
    return _client


async def chat_structured(
    cfg: AppConfig, output_type: type[ModelT], system: str, user: str, *, timeout: float = 10.0
) -> ModelT:
    """单次结构化调用：system+user → output_type 实例（MUST-13：wait_for 超时）。"""
    _ensure_client(cfg)
    agent = Agent(
        name="devprompt-llm",
        instructions=system,
        output_type=output_type,
        model=cfg.llm_model,
    )
    result = await asyncio.wait_for(Runner.run(agent, user, max_turns=1), timeout=timeout)
    output = result.final_output
    if not isinstance(output, output_type):
        raise GenerationError(
            "LLM 返回结构不符合预期契约",
            code=4003,
            context={"actual_type": type(output).__name__},
        )
    return output
