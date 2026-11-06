"""多供应商 LLM 封装（F-004）：按 provider 分流 API 形态 + 禁 tracing。

2026-09-17 多供应商扩展：**不再使用进程级全局开关** `set_default_openai_api`。
该开关是模块级单例，Web 并发下按「当前 provider」反复设置会相互覆盖
（A 请求设 responses、B 请求设 chat_completions → 随机 4xx）。改为
:func:`build_model` **按调用构造 Model 实例**，每个 Agent 持有自己的形态，
互不影响。SDK 侧 `set_default_openai_client` 与 `set_tracing_disabled` 仍保留
（前者幂等，后者与协议无关）。

结构化输出仍采用 prompt 注入 schema + 本地解析校验（不依赖供应商 response_format，
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
    Model,
    ModelSettings,
    Runner,
    set_default_openai_client,
    set_tracing_disabled,
)
from agents.models.interface import ModelTracing
from agents.tool import FunctionTool
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from devprompt_ai.common.cost import add_llm_tokens
from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.error_codes import registered
from devprompt_ai.domain.errors import ConfigurationError, GenerationError
from devprompt_ai.domain.generate.ports import (
    VALID_LEVEL_SETS,
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.domain.model_spec import resolve_api_mode
from devprompt_ai.domain.prompt_guard import (
    JSON_STRICT_RULES,
    build_evidence_block,
)
from devprompt_ai.harness.adapters import adapter_kind_for, build_adapter
from devprompt_ai.harness.ask_tool import ASK_TOOL_DEFINITION, ASK_TOOL_NAME

ModelT = TypeVar("ModelT", bound=BaseModel)

_last_usage: ContextVar[dict[str, int | None] | None] = ContextVar("last_usage", default=None)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """从模型输出提取 JSON 主体：剥围栏 / 截取首尾花括号（供应商输出习惯差异兜底）。"""
    # shortcut: 首尾截取仅在「输出恰好是一个对象、且尾部无任何右括号」时成立。
    # 2026-10-16 真实统计 40 次调用（含项目真实三套生成 prompt）测得该脆弱形态
    # 命中率 0/40，故不实现括号配平状态机。
    # 升级路径：若 scripts/probe_llm_output_shape.py --real-prompt 换供应商后测得
    # 解析失败 > 0，再实施配平状态机（离线样本见 scripts/probe_json_extraction.py）。
    text = text.strip()
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def last_usage() -> dict[str, int | None] | None:
    """F-805 成本监控起建：返回最近一次结构化调用的 token 用量。

    ``cached_tokens`` 为 None 表示供应商未返回缓存命中信息——**不虚报 0**。
    """
    return _last_usage.get()


def _cached_tokens(usage: object) -> int | None:
    """读取供应商返回的缓存命中 token；无该字段返回 None。

    兼容两种形态：SDK 对象（``usage.prompt_tokens_details.cached_tokens``）与
    原生适配器返回的 dict。
    """
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is None:
        return None
    value = getattr(details, "cached_tokens", None)
    if value is None and isinstance(details, dict):
        value = details.get("cached_tokens")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_usage(usage: object | None) -> None:
    """记录一次调用的 token 用量：last（最近一次，兼容旧调用方）+ 累计待取（F-805）。"""
    if usage is None:
        _last_usage.set(None)
        return
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    _last_usage.set({"total_tokens": total_tokens, "cached_tokens": _cached_tokens(usage)})
    add_llm_tokens(total_tokens)


_client: AsyncOpenAI | None = None
#: 已构造 client 的缓存键（model, base_url, api_key）；三者任一变化必重建。
_client_key: tuple[str, str, str] | None = None


def _ensure_client(cfg: AppConfig) -> AsyncOpenAI:
    """惰性初始化 OpenAI 兼容客户端（同一 model 只构造一次）。

    **刻意不调 `set_default_openai_api`**：那是进程级单例，Web 并发下按 provider
    反复设置会相互覆盖（A 请求设 responses、B 请求设 chat_completions → 随机 4xx）。
    API 形态改为**按调用注入 Model 实例**，见 :func:`build_model`。
    """
    global _client, _client_key
    if not cfg.llm_base_url or not cfg.llm_model:
        raise ConfigurationError(
            "LLM 未配置：需要 LLM_BASE_URL / LLM_MODEL 环境变量",
            context={
                "llm_base_url_set": bool(cfg.llm_base_url),
                "llm_model_set": bool(cfg.llm_model),
            },
        )
    # 缓存键必须含**端点与密钥**：只按 model 键会让「同一 model id 换了端点/密钥」
    # 复用旧 client（旧代码就有这个缺陷）——api_mode 生效后用户按条目切换端点会直接踩到该处。
    key = (cfg.llm_model, cfg.llm_base_url, cfg.llm_api_key)
    if _client is None or _client_key != key:
        _client = AsyncOpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key or "EMPTY")
        set_default_openai_client(_client)
        set_tracing_disabled(True)  # 第三方 key 走 tracing 会 401
        _client_key = key
    return _client


def build_model(cfg: AppConfig) -> Model:
    """按当前 provider 的 `api_mode` 构造 Model 实例（逐调用，无共享状态）。

    这是「按 provider 分流协议形态」的唯一入口：

    - `chat_completions` → `OpenAIChatCompletionsModel`（绝大多数第三方厂商）
    - `responses` → `OpenAIResponsesModel`（OpenAI 官方）
    - `anthropic_messages` / `gemini_generate_content` → 原生 `Model` 子类

    之所以不走 `set_default_openai_api` 全局开关：该开关是模块级单例，Web 并发
    多请求下按「当前 provider」反复设置会产生竞态。按调用构造实例则无此问题——
    每个 Agent 持有自己的 Model，互不影响。

    :param cfg: 应用配置（读 `llm_provider` / `llm_model` / `llm_api_key`）
    """
    client = _ensure_client(cfg)
    api_mode = resolve_api_mode(cfg.llm_provider or "", cfg.api_mode or "")
    return build_adapter(
        adapter_kind_for(api_mode),
        cfg.llm_model,
        client,
        api_key=cfg.llm_api_key or "",
        base_url=cfg.llm_base_url,
        api_mode=api_mode,
    )


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
    instructions = f"{system}\n\n{JSON_STRICT_RULES}\n且必须符合如下 JSON Schema：\n{schema}"
    agent = Agent(
        name="devprompt-llm",
        instructions=instructions,
        model=build_model(cfg),
        model_settings=ModelSettings(
            **cfg.effective_llm_params(),
            # reasoning_effort 等 ModelSettings 未建模的参数走 extra_body 真正下发
            extra_body=cfg.extra_body_params() or None,
        ),
    )
    try:
        result = await asyncio.wait_for(
            Runner.run(agent, user, max_turns=1), timeout=effective_timeout
        )
    except Exception as exc:
        # LLM 调用失败 → 细分错误码（5011~5015），供前端给精确文案（M-9）
        raise _llm_failure_error(exc, cfg, output_type) from exc
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
    try:
        result2 = await asyncio.wait_for(
            Runner.run(agent, retry_input, max_turns=1), timeout=effective_timeout
        )
    except Exception as exc:
        raise _llm_failure_error(exc, cfg, output_type) from exc
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

#: 各档约束的文案键（2026-11-06 双语；文案在 common/i18n.py 的 template.tier.*）。
_TIER_KEYS: Final[dict[str, str]] = {
    "A": "template.tier.a",
    "B": "template.tier.b",
    "C": "template.tier.c",
}

_LEVEL_RANK: Final[dict[str, int]] = {"A": 0, "B": 1, "C": 2}


def _build_multi_system(levels: list[Level], locale: Locale = DEFAULT_LOCALE) -> str:
    """按请求档位裁剪模板约束（levels 决定要求几套），并注入一致性与梯度约束。"""
    ordered = sorted(levels)
    tiers = tr("template.multi.tiers_sep", locale).join(
        tr(_TIER_KEYS[lv], locale) for lv in ordered
    )
    return (
        tr(
            "template.multi.role",
            locale,
            count=len(ordered),
            levels=tr("common.list_sep", locale).join(ordered),
        )
        + "\n"
        + tr("template.multi.tiers", locale, tiers=tiers)
        + "\n"
        + tr("template.multi.consistency", locale)
        + tr("template.body_semantics", locale)
    )


def _build_multi_user(
    ctx: GenerationContext, levels: list[Level], locale: Locale = DEFAULT_LOCALE
) -> str:
    """用户消息：证据走 JSON 块 + 安全声明（M-5），指令在首尾。

    证据字段含检索到的真实代码摘要——其中的注释/字符串可能包含指令性文本，
    故必须经`build_evidence_block` 包裹并声明「只是素材」。
    """
    evidence = build_evidence_block(
        {
            tr("template.field.request", locale): ctx.sentence,
            tr("template.field.facts", locale): (
                ctx.facts_summary or tr("template.field.none_facts", locale)
            ),
            tr("template.field.clarifications", locale): ctx.clarifications,
            tr("template.field.conservative", locale): ctx.conservative,
            # 多轮（2026-10-20）：历史结论与记忆由 build_context 装配，缺省为空不出现
            tr("template.field.history", locale): (
                ctx.history_block or tr("template.field.none_history", locale)
            ),
            tr("template.field.memory", locale): (
                ctx.memory_block or tr("template.field.none_facts_plain", locale)
            ),
            # 多轮（2026-11-04）：上一轮方案正文，供「在已有方案上改」的轮次引用
            tr("template.field.previous_variants", locale): (
                ctx.previous_variants or tr("template.field.none_variants", locale)
            ),
        }
    )
    return (
        tr("template.multi.request_levels", locale, levels=sorted(levels))
        + "\n"
        + evidence
        + "\n"
        + tr("template.instruction_prefix", locale)
        + '{"variants": [{"title": "...", "body": "...", '
        '"changes": ["..."], "level": "A", '
        '"claims": [{"kind": "file|symbol|token|line|absence", "target": "...", '
        '"negates": "file|symbol|token|line"}]}]}\n' + tr("template.multi.claims_rules", locale)
    )


class LLMGenerator:
    """GeneratePort 的 LLM 实现（F-301：单套 generate_single + 三套同次调用 generate_variants）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def generate_single(
        self, ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE
    ) -> VariantDraft:
        from devprompt_ai.domain.generate.templates import TEMPLATE_BY_LEVEL
        from devprompt_ai.harness.guardrails import validate_variant

        tpl = TEMPLATE_BY_LEVEL[ctx.level]
        # 生成类调用输出长（完整方案正文）：timeout 缺省即 cfg.llm_timeout（F-604，默认 60s；
        # 10s 会截断真实生成——4H 端到端实测）
        draft = await chat_structured(
            self._cfg,
            VariantDraft,
            tpl.system(locale),
            tpl.build_user(ctx, locale),
        )
        validate_variant(draft)
        return draft

    async def answer(self, ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
        """纯回答（2026-11-05）：一次结构化调用，只取正文。

        与 generate_single 的唯一差别是输出模型——``ReplyOutput`` 没有
        title/changes/level/claims 字段，从类型上就不可能是方案。
        """
        from devprompt_ai.domain.generate.ports import ReplyOutput
        from devprompt_ai.domain.generate.templates import reply as reply_tpl

        out = await chat_structured(
            self._cfg,
            ReplyOutput,
            reply_tpl.system_text(locale),
            reply_tpl.build_user(ctx, locale),
        )
        return out.text

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level], locale: Locale = DEFAULT_LOCALE
    ) -> MultiVariantDraft:
        """三套（或裁剪后 1~3 套）同次调用生成（F-301；T5-1/T5-2）。

        契约：levels 由调用方按 resolve_level 推导（A→["A"]、B→["A","B"]、C→["A","B","C"]，
        见 domain/generate/variants.expand_levels；escape/护栏保守路径请求 ["A"]）；
        输出档位允许为请求的非空子集（U-7：套数不足按实际套数交付，交付门披露），
        超出请求范围或非法前缀集仍拒绝（MUST-28 不越级输出），返回按 A<B<C 单调排序。
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
            _build_multi_system(levels, locale),
            _build_multi_user(ctx, levels, locale),
        )
        got = frozenset(v.level for v in draft.variants)
        # U-7（2026-11-06 业主裁定）：套数不足不再整单失败——接受请求档位的非空子集，
        # 交付门按实际套数披露（MUST-30 只降标记不阻断）；非法前缀集（如 {A,C}）
        # 仍被 MultiVariantDraft 结构层拒绝，走 4003 纠偏重试。
        if not got <= level_set:
            raise GenerationError(
                "三套输出档位超出请求范围",
                code=4003,
                context={"requested": sorted(level_set), "got": sorted(got)},
            )
        from devprompt_ai.harness.guardrails import validate_variant

        for variant in draft.variants:
            validate_variant(variant)
        draft.variants.sort(key=lambda v: _LEVEL_RANK[v.level])
        return draft


#: LLM 调用失败场景 → 错误码（用户 2026-10-16 裁定：细分 5 个码，前端给精确文案）。
#: 5012 与 3004 的区别：3004 是决策阶段限流，本表是生成阶段（chat_structured）限流。
_LLM_FAILURE_CODES: Final[dict[str, int]] = {
    "timeout": registered(5011),
    "rate_limit": registered(5012),
    "insufficient_quota": registered(5013),
    "invalid_api_key": registered(5014),
    "upstream_error": registered(5015),
}

#: 错误文本特征 → 场景（按出现顺序匹配，顺序即优先级：额度/鉴权须先于限流判断）
_SCENARIO_SIGNALS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "insufficient_quota",
        ("insufficient", "quota", "balance", "余额", "配额", "欠费", "billing"),
    ),
    (
        "invalid_api_key",
        ("invalid api key", "incorrect api key", "unauthorized", "authentication", "鉴权", "密钥"),
    ),
    ("rate_limit", ("rate limit", "ratelimit", "too many requests", "429", "限流", "频率")),
    (
        "upstream_error",
        (
            "500",
            "502",
            "503",
            "504",
            "internal server",
            "bad gateway",
            "服务暂时不可用",
            # 网络类异常（用户裁定：server_error_500 与 network_error 共用 5015）
            "connection",
            "connect error",
            "unreachable",
            "network",
            "dns",
            "getaddrinfo",
            "socket",
            "ssl",
        ),
    ),
)


def classify_llm_failure(exc: BaseException) -> tuple[str, int] | None:
    """把 LLM 调用异常归类为 ``(场景名, 错误码)``；无法归类返回 None。

    归类顺序：先判超时（`asyncio.TimeoutError`），再按文本特征匹配。
    **纯文本匹配，不依赖 SDK 异常类型**——各供应商 SDK 的异常层级与命名不一致
    （openai / httpx / agents 各自包装），文本特征是唯一稳定信号。
    """
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout", _LLM_FAILURE_CODES["timeout"]
    haystack = f"{type(exc).__name__} {exc}".lower()
    for scenario, signals in _SCENARIO_SIGNALS:
        if any(signal in haystack for signal in signals):
            return scenario, _LLM_FAILURE_CODES[scenario]
    return None


#: 场景 → 用户可读文案（前端另持本地化文案表，此处供日志与 message 使用）
_LLM_FAILURE_MESSAGES: Final[dict[str, str]] = {
    "timeout": "LLM 调用超时，请稍后重试或调大 LLM_TIMEOUT",
    "rate_limit": "供应商限流，请稍后重试",
    "insufficient_quota": "供应商余额或配额不足，请充值后重试",
    "invalid_api_key": "LLM 鉴权失败，请检查 API Key 是否正确",
    "upstream_error": "LLM 上游服务异常，请稍后重试",
}


def _llm_failure_error(exc: BaseException, cfg: AppConfig, output_type: type[object]) -> Exception:
    """把 LLM 调用异常转为带细分码的 GenerationError；无法归类则回退 4002。

    `context["scenario"]` 是**可判别字段**，供上层分支与日志检索（MUST-03）；
    message 只给用户可读文案，**不回显异常原文**（可能含请求片段或密钥，MUST-19）。
    """
    classified = classify_llm_failure(exc)
    context: dict[str, object] = {
        "model": cfg.llm_model,
        "output_type": getattr(output_type, "__name__", str(output_type)),
    }
    if classified is None:
        return GenerationError(
            "LLM 端点不可达或调用失败",
            code=registered(4002),
            context={**context, "scenario": "unclassified"},
        )
    scenario, code = classified
    return GenerationError(
        _LLM_FAILURE_MESSAGES[scenario],
        code=code,
        context={**context, "scenario": scenario},
    )


def _text_of(output: object) -> str:
    """从 ModelResponse.output 提取助手文本（兼容 SDK 对象与原生适配器的 dict）。"""
    parts: list[str] = []
    for item in output if isinstance(output, list) else []:
        if isinstance(item, dict):
            if item.get("type") != "message":
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    parts.append(str(block.get("text") or ""))
            continue
        if getattr(item, "type", "") != "message":
            continue
        for block in getattr(item, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
    return "".join(parts)


class ToolCallRequest(BaseModel):
    """一次工具调用的原始参数（不含密钥/原句，可安全落会话）。"""

    call_id: str = ""
    name: str
    arguments: str = ""


class ToolChatResult(BaseModel):
    """带工具的调用结果：要么拿到 tool_call，要么拿到文本（供 _parse_model）。"""

    tool_call: ToolCallRequest | None = None
    text: str = ""


async def _noop_invoke(_ctx: object, _args: str) -> str:
    """占位实现：本模块只取 function_call，不执行工具（作答在流程里由用户完成）。"""
    return ""


def _ask_function_tool() -> FunctionTool:
    """构造 AskUserQuestion 的 FunctionTool（仅用于让模型产出 function_call）。"""
    return FunctionTool(
        name=ASK_TOOL_NAME,
        description=str(ASK_TOOL_DEFINITION["function"]["description"]),
        params_json_schema=ASK_TOOL_DEFINITION["function"]["parameters"],
        on_invoke_tool=_noop_invoke,
        # 我们的 schema 带 maxLength/minItems 等描述性约束，不满足 strict 模式的全字段 required 要求
        strict_json_schema=False,
    )


def _first_function_call(output: list[object]) -> ToolCallRequest | None:
    """从 ModelResponse.output 取第一个 function_call。

    原生适配器（anthropic/gemini）返回的是普通 dict，SDK 适配器返回
    ``ResponseFunctionToolCall`` 实例——两种形态都要认。
    """
    for item in output:
        if isinstance(item, dict):
            if item.get("type") == "function_call":
                return ToolCallRequest(
                    call_id=str(item.get("call_id") or ""),
                    name=str(item.get("name") or ""),
                    arguments=str(item.get("arguments") or ""),
                )
            continue
        if getattr(item, "type", "") == "function_call":
            return ToolCallRequest(
                call_id=str(getattr(item, "call_id", "") or ""),
                name=str(getattr(item, "name", "") or ""),
                arguments=str(getattr(item, "arguments", "") or ""),
            )
    return None


def parse_structured(output_type: type[ModelT], raw: str) -> ModelT | None:
    """把模型文本解析成结构化输出（复用 chat_structured 的容错口径）。"""
    return _parse_model(output_type, raw)


async def chat_with_tools(
    cfg: AppConfig,
    system: str,
    user: str,
    *,
    timeout: float | None = None,
) -> ToolChatResult:
    """单次带工具调用：模型可回 function_call（AskUserQuestion），否则回文本。

    刻意**不用 Runner**：``Runner.run(max_turns=1)`` 在模型发起工具调用时会自动执行
    工具并继续，用满轮数只会抛 ``MaxTurnsExceeded``，拿不到稳定的 call 参数。
    这里直接调 ``Model.get_response``，工具不会被真正执行（``on_invoke_tool`` 是空桩）。

    四种 provider 都能传 tools 并解析 function_call；但 anthropic/gemini 原生适配器
    不支持回喂 ``function_call_output``，因此答案不通过 tool result 回传，而是由调用方
    重建 prompt 携带「已答问题 + 答案」（见 decision/fallback.py）。
    """
    model = build_model(cfg)
    settings = ModelSettings(tool_choice="auto")
    effective_timeout = timeout if timeout is not None else cfg.llm_timeout
    try:
        response = await asyncio.wait_for(
            model.get_response(
                system_instructions=system,
                input=user,
                model_settings=settings,
                tools=[_ask_function_tool()],
                output_schema=None,
                handoffs=[],
                tracing=ModelTracing.DISABLED,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            ),
            timeout=effective_timeout,
        )
    except Exception as exc:
        raise _llm_failure_error(exc, cfg, ToolChatResult) from exc

    _record_usage(getattr(response, "usage", None))
    tool_call = _first_function_call(list(response.output))
    if tool_call is not None:
        return ToolChatResult(tool_call=tool_call)
    return ToolChatResult(text=_text_of(response.output))
