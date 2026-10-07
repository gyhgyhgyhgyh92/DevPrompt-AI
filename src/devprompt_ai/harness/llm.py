"""多供应商 LLM 封装（F-004）：OpenAI 兼容协议 + Chat Completions + 禁 tracing。

SDK 三约束（技术栈 §4.5）：set_default_openai_api("chat_completions")；
set_tracing_disabled(True)；base_url 经 set_default_openai_client 注入。
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
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
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft

ModelT = TypeVar("ModelT", bound=BaseModel)

_last_usage: ContextVar[dict[str, int] | None] = ContextVar("last_usage", default=None)


def last_usage() -> dict[str, int] | None:
    """F-805 成本监控起建：返回最近一次结构化调用的 token 用量。"""
    return _last_usage.get()


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
    usage = getattr(result, "usage", None)
    _last_usage.set(
        {"total_tokens": int(getattr(usage, "total_tokens", 0) or 0)} if usage else None
    )
    output = result.final_output
    if not isinstance(output, output_type):
        raise GenerationError(
            "LLM 返回结构不符合预期契约",
            code=4003,
            context={"actual_type": type(output).__name__},
        )
    return output


class LLMGenerator:
    """GeneratePort 的 LLM 实现（F-301 单套；三套编排阶段五在 variants 扩展）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def generate_single(self, ctx: GenerationContext) -> VariantDraft:
        from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL
        from devprompt_ai.harness.guardrails import validate_variant

        tpl = TEMPLATE_BY_LEVEL[ctx.level]
        draft = await chat_structured(self._cfg, VariantDraft, tpl.system, tpl.build_user(ctx))
        validate_variant(draft)
        return draft
