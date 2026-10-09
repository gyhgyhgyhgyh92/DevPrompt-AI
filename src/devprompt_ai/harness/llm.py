"""多供应商 LLM 封装（F-004）：OpenAI 兼容协议 + Chat Completions + 禁 tracing。

SDK 三约束（技术栈 §4.5）：set_default_openai_api("chat_completions")；
set_tracing_disabled(True)；base_url 经 set_default_openai_client 注入。
结构化输出采用 prompt 注入 schema + 本地解析校验（不依赖供应商 response_format，
DeepSeek 等端点不支持 json_schema response_format——2026-10-09 实测）。
"""

from __future__ import annotations

import asyncio
import json
import re
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
from pydantic import BaseModel, ValidationError

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import ConfigurationError, GenerationError
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft

ModelT = TypeVar("ModelT", bound=BaseModel)

_last_usage: ContextVar[dict[str, int] | None] = ContextVar("last_usage", default=None)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """从模型输出提取 JSON 主体：剥围栏 / 截取首尾花括号（供应商输出习惯差异兜底）。"""
    text = text.strip()
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


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
    """单次结构化调用：system+user → output_type 实例（MUST-13：wait_for 超时）。

    F-004 适配：prompt 注入 JSON Schema，本地解析 + pydantic 校验 + 一次纠偏重试——
    不依赖供应商 response_format（实测 DeepSeek 400: response_format type unavailable）。
    """
    _ensure_client(cfg)
    schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
    instructions = (
        f"{system}\n\n"
        "输出要求：只输出一个 JSON 对象（无 markdown 围栏、无解释文字），"
        f"且必须符合如下 JSON Schema：\n{schema}"
    )
    agent = Agent(name="devprompt-llm", instructions=instructions, model=cfg.llm_model)
    result = await asyncio.wait_for(Runner.run(agent, user, max_turns=1), timeout=timeout)
    usage = getattr(result, "usage", None)
    _last_usage.set(
        {"total_tokens": int(getattr(usage, "total_tokens", 0) or 0)} if usage else None
    )
    raw = str(result.final_output)
    parsed = _parse_model(output_type, raw)
    if parsed is not None:
        return parsed
    # 纠偏重试一次：把首轮输出与解析失败原因回喂，要求修正为纯 JSON
    retry_input = (
        f"{user}\n\n你上一轮输出无法解析为符合 Schema 的 JSON，原样如下：\n{raw[:2000]}\n\n"
        "请修正：只输出一个符合 Schema 的 JSON 对象，无围栏无解释。"
    )
    result2 = await asyncio.wait_for(Runner.run(agent, retry_input, max_turns=1), timeout=timeout)
    usage2 = getattr(result2, "usage", None)
    _last_usage.set(
        {"total_tokens": int(getattr(usage2, "total_tokens", 0) or 0)} if usage2 else None
    )
    parsed2 = _parse_model(output_type, str(result2.final_output))
    if parsed2 is None:
        raise GenerationError(
            "LLM 两次输出均无法解析为约定 JSON 结构",
            code=4003,
            context={"model": cfg.llm_model, "output_type": output_type.__name__},
        )
    return parsed2


def _parse_model(output_type: type[ModelT], raw: str) -> ModelT | None:
    """解析并校验模型输出；失败返回 None（由调用方决定重试或报错）。"""
    try:
        return output_type.model_validate_json(_extract_json(raw))
    except ValidationError:
        return None


class LLMGenerator:
    """GeneratePort 的 LLM 实现（F-301 单套；三套编排阶段五在 variants 扩展）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def generate_single(self, ctx: GenerationContext) -> VariantDraft:
        from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL
        from devprompt_ai.harness.guardrails import validate_variant

        tpl = TEMPLATE_BY_LEVEL[ctx.level]
        # 生成类调用输出长（完整方案正文），10s 默认超时会截断真实生成（4H 端到端实测）
        draft = await chat_structured(
            self._cfg, VariantDraft, tpl.system, tpl.build_user(ctx), timeout=60.0
        )
        validate_variant(draft)
        return draft
