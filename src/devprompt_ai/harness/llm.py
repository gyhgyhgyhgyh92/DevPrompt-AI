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
from typing import Final, TypeVar

from agents import (
    Agent,
    ModelSettings,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from devprompt_ai.common.cost import add_llm_tokens
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import ConfigurationError, GenerationError
from devprompt_ai.domain.generate.ports import (
    VALID_LEVEL_SETS,
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)

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


def _record_usage(usage: object | None) -> None:
    """记录一次调用的 token 用量：last（最近一次，兼容旧调用方）+ 累计待取（F-805）。"""
    if usage is None:
        _last_usage.set(None)
        return
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    _last_usage.set({"total_tokens": total_tokens})
    add_llm_tokens(total_tokens)


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
    cfg: AppConfig,
    output_type: type[ModelT],
    system: str,
    user: str,
    *,
    timeout: float | None = None,
) -> ModelT:
    """单次结构化调用：system+user → output_type 实例（MUST-13：wait_for 超时）。

    timeout 缺省取 cfg.llm_timeout（F-604 可配置；小证据探针等调用方可显式传短超时）；
    温度/max_tokens 经 ModelSettings 下发（未设则不下发，走供应商默认）。
    F-004 适配：prompt 注入 JSON Schema，本地解析 + pydantic 校验 + 一次纠偏重试——
    不依赖供应商 response_format（实测 DeepSeek 400: response_format type unavailable）。
    """
    _ensure_client(cfg)
    effective_timeout = timeout if timeout is not None else cfg.llm_timeout
    schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
    instructions = (
        f"{system}\n\n"
        "输出要求：只输出一个 JSON 对象（无 markdown 围栏、无解释文字），"
        f"且必须符合如下 JSON Schema：\n{schema}"
    )
    agent = Agent(
        name="devprompt-llm",
        instructions=instructions,
        model=cfg.llm_model,
        model_settings=ModelSettings(
            temperature=cfg.llm_temperature, max_tokens=cfg.llm_max_tokens
        ),
    )
    result = await asyncio.wait_for(Runner.run(agent, user, max_turns=1), timeout=effective_timeout)
    _record_usage(getattr(result, "usage", None))
    raw = str(result.final_output)
    parsed = _parse_model(output_type, raw)
    if parsed is not None:
        return parsed
    # 纠偏重试一次：把首轮输出与解析失败原因回喂，要求修正为纯 JSON
    retry_input = (
        f"{user}\n\n你上一轮输出无法解析为符合 Schema 的 JSON，原样如下：\n{raw[:2000]}\n\n"
        "请修正：只输出一个符合 Schema 的 JSON 对象，无围栏无解释。"
    )
    result2 = await asyncio.wait_for(
        Runner.run(agent, retry_input, max_turns=1), timeout=effective_timeout
    )
    _record_usage(getattr(result2, "usage", None))
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


# ---- 三套同次调用模板（T5-2：F-302/303/304 档位约束 + F-301 一致性约束；按请求档位裁剪）----

_TIER_CONSTRAINTS: Final[dict[str, str]] = {
    "A": (
        "A 保守版：只陈述用户意图与可执行要点，明确改动范围边界，结尾附待确认清单"
        "（缺什么列什么）；禁止出现任何行号，禁止编造未取证的文件路径与选择器。"
    ),
    "B": (
        "B 标准版：给出已取证的文件路径与选择器，明确变更边界（改什么、不改什么）；"
        "推断项必须以「（推断）」字样显式标注；包含验证方式（跑什么测试、出什么 diff）；"
        "禁止编造未提供的行号。"
    ),
    "C": (
        "C 激进版：给出完整路径、行号、组件名与设计 token 定义位置；"
        "边界预判必须覆盖多状态、响应式、暗色模式、无障碍；"
        "结尾附显式测试指令（含测试文件路径）。"
    ),
}

_LEVEL_RANK: Final[dict[str, int]] = {"A": 0, "B": 1, "C": 2}


def _build_multi_system(levels: list[Level]) -> str:
    """按请求档位裁剪模板约束（levels 决定要求几套），并注入一致性与梯度约束。"""
    ordered = sorted(levels)
    tiers = "\n".join(f"- {_TIER_CONSTRAINTS[lv]}" for lv in ordered)
    return (
        f"你是提示词优化师。基于同一份上下文，一次性输出 {len(ordered)} 套提示词方案，"
        f"请求档位为 {'、'.join(ordered)}。\n"
        "各档位模板约束：\n"
        f"{tiers}\n"
        "一致性约束：所有方案共享同一份事实基础，同一事实在各套中的描述必须一致"
        "（禁止信息漂移）；各套正文长度与详细度必须呈明显梯度（A 最短、C 最长）。\n"
        "除请求档位外不得多套、少套或改用其他档位。只输出 JSON。"
    )


def _build_multi_user(ctx: GenerationContext, levels: list[Level]) -> str:
    return (
        f"请求档位（逐一输出，顺序 A→B→C）：{sorted(levels)}\n"
        f"用户需求：{ctx.sentence}\n"
        f"取证摘要：{ctx.facts_summary or '（无，禁止编造路径与行号）'}\n"
        f"已澄清信息：{json.dumps(ctx.clarifications, ensure_ascii=False)}\n"
        f"保守模式：{ctx.conservative}\n"
        '请输出 JSON：{"variants": [{"title": "...", "body": "...", '
        '"changes": ["..."], "level": "A"}]}，variants 数组长度与档位必须与请求档位一致。'
    )


class LLMGenerator:
    """GeneratePort 的 LLM 实现（F-301：单套 generate_single + 三套同次调用 generate_variants）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def generate_single(self, ctx: GenerationContext) -> VariantDraft:
        from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL
        from devprompt_ai.harness.guardrails import validate_variant

        tpl = TEMPLATE_BY_LEVEL[ctx.level]
        # 生成类调用输出长（完整方案正文）：timeout 缺省即 cfg.llm_timeout（F-604，默认 60s；
        # 10s 会截断真实生成——4H 端到端实测）
        draft = await chat_structured(self._cfg, VariantDraft, tpl.system, tpl.build_user(ctx))
        validate_variant(draft)
        return draft

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level]
    ) -> MultiVariantDraft:
        """三套（或裁剪后 1~3 套）同次调用生成（F-301；T5-1/T5-2）。

        契约：levels 由调用方按 resolve_level 推导（A→["A"]、B→["A","B"]、C→["A","B","C"]，
        见 domain/generate/variants.expand_levels；escape/护栏保守路径请求 ["A"]）；
        输出档位集合必须与请求一致，返回按 A<B<C 单调排序（MUST-28 不越级输出）。
        单次 chat_structured 调用（timeout 缺省即 cfg.llm_timeout；纠偏重试内聚）。
        """
        level_set = frozenset(levels)
        if len(level_set) != len(levels) or level_set not in VALID_LEVEL_SETS:
            raise GenerationError(
                "generate_variants 请求档位非法：须为无重复的 A 前缀集（MUST-28）",
                code=4003,
                context={"levels": sorted(level_set)},
            )
        draft = await chat_structured(
            self._cfg,
            MultiVariantDraft,
            _build_multi_system(levels),
            _build_multi_user(ctx, levels),
        )
        got = frozenset(v.level for v in draft.variants)
        if got != level_set:
            raise GenerationError(
                "三套输出档位与请求不符",
                code=4003,
                context={"requested": sorted(level_set), "got": sorted(got)},
            )
        from devprompt_ai.harness.guardrails import validate_variant

        for variant in draft.variants:
            validate_variant(variant)
        draft.variants.sort(key=lambda v: _LEVEL_RANK[v.level])
        return draft
