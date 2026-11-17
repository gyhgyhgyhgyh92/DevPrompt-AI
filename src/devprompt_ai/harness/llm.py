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
import logging
import re
import time
from collections.abc import Hashable, Mapping
from contextvars import ContextVar, Token
from typing import Any, Final, Literal, TypeVar, cast

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

from devprompt_ai.common.cost import add_llm_usage
from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.context.budget import (
    RequestBudgetError,
    ensure_request_fits,
    request_budget,
)
from devprompt_ai.domain.context.tokens import estimate_tokens
from devprompt_ai.domain.error_codes import registered
from devprompt_ai.domain.errors import ConfigurationError, DevPromptError, GenerationError
from devprompt_ai.domain.generate.ports import (
    GenerationContext,
    VariantDraft,
)
from devprompt_ai.domain.model.tuning import resolve_effort
from devprompt_ai.domain.model_spec import (
    max_context_length_of,
    model_meta_of,
    resolve_api_mode,
)
from devprompt_ai.domain.progress import ProgressEvent, ProgressSink
from devprompt_ai.domain.prompt_guard import (
    JSON_STRICT_RULES,
    family_note,
)
from devprompt_ai.harness.adapters import adapter_kind_for, build_adapter
from devprompt_ai.harness.ask_tool import ASK_TOOL_DEFINITION, ASK_TOOL_NAME
from devprompt_ai.harness.model_candidates import load_candidates
from devprompt_ai.harness.model_pool import ModelPool
from devprompt_ai.harness.retry import (
    RetryBudget,
    RetryPolicy,
    abortable_sleep,
    next_delay,
)
from devprompt_ai.memory.routing_stats import SQLiteRoutingStats
from devprompt_ai.memory.settings_store import read_model_registry
from devprompt_ai.observability.logging import emit, emit_error

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_last_usage: ContextVar[dict[str, int | None] | None] = ContextVar("last_usage", default=None)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

#: 重试策略与共享预算（A11）：所有结构化调用共用，避免 provider × agent 相乘。
_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy()
_RETRY_BUDGET: Final[RetryBudget] = RetryBudget(capacity=5, window_s=60.0)

#: 生成阶段的增量推送出口（2026-11-15 流式）：用 ContextVar 隔离到当前请求 task，
#: 避免为改协议签名牵动 GeneratePort 与全部测试替身。
_GENERATION_SINK: ContextVar[ProgressSink | None] = ContextVar(
    "devprompt_generation_sink", default=None
)
#: 增量推送节流：过密会把 SSE 刷爆，过疏则打字机断断续续。
_STREAM_EMIT_INTERVAL_S: Final[float] = 0.25
#: 每次推送保留的尾部字符数（前端只展示「正在写什么」）。
_STREAM_TAIL_CHARS: Final[int] = 120


def set_generation_sink(sink: ProgressSink | None) -> Token[ProgressSink | None]:
    """设置本轮生成的增量推送出口；调用方负责在 finally 中 ``reset_generation_sink``。"""
    return _GENERATION_SINK.set(sink)


def reset_generation_sink(token: Token[ProgressSink | None]) -> None:
    _GENERATION_SINK.reset(token)


async def _run_streamed_generate(agent: Agent, payload: str | list[Any], timeout: float) -> Any:
    """生成路径流式累积：增量文本节流推思考帧，完整输出仍由调用方解析（协议不变）。

    首字延迟从「等完整 JSON」降到首个 delta；超时语义与原 ``wait_for`` 一致。
    """
    sink = _GENERATION_SINK.get()
    result = Runner.run_streamed(agent, payload, max_turns=1)

    async def consume() -> Any:
        buffer: list[str] = []
        last_emit = 0.0
        async for event in result.stream_events():
            if sink is None or getattr(event, "type", "") != "raw_response_event":
                continue
            delta = getattr(getattr(event, "data", None), "delta", None)
            if not isinstance(delta, str) or not delta:
                continue
            buffer.append(delta)
            now = time.monotonic()
            if now - last_emit < _STREAM_EMIT_INTERVAL_S:
                continue
            last_emit = now
            text = "".join(buffer)[-_STREAM_TAIL_CHARS:]
            buffer.clear()
            await sink.emit(ProgressEvent(text=text, phase="GENERATING"))
        # 收尾 flush：短输出全程未触发节流时也要把内容推出去（否则前端一直空白）
        if sink is not None and buffer:
            await sink.emit(
                ProgressEvent(text="".join(buffer)[-_STREAM_TAIL_CHARS:], phase="GENERATING")
            )
        return result

    return await asyncio.wait_for(consume(), timeout=timeout)
_RETRYABLE_MARKERS: Final[tuple[str, ...]] = (
    "timeout",
    "429",
    "500",
    "502",
    "503",
    "504",
    "rate limit",
    "connection",
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in _RETRYABLE_MARKERS)


def _user_payload(user: str, images: tuple[str, ...]) -> str | list[Any]:
    """纯文本走 str（零回归）；带参考图时构造 agents 标准的 user message items。

    dict 形态的 ``input_image`` item 由 openai 系 SDK 与两个原生 adapter 各自转换
    （2026-11-14 多模态）。
    """
    if not images:
        return user
    content: list[dict[str, Any]] = [{"type": "input_text", "text": user}]
    content.extend({"type": "input_image", "image_url": img} for img in images)
    return [{"role": "user", "content": content}]


async def _run_with_retry(
    agent: Agent,
    payload: str | list[Any],
    timeout: float,
    *,
    retry_on_timeout: bool = True,
) -> Any:
    """带退避与共享预算的单次结构化调用（失败抛原始异常，由调用方归类）。

    ``retry_on_timeout=False``：超时直接抛（生成路径用）——重试会与兜底模板叠加。
    """
    for attempt in range(1, _RETRY_POLICY.max_attempts + 1):
        try:
            return await asyncio.wait_for(Runner.run(agent, payload, max_turns=1), timeout=timeout)
        except Exception as exc:
            timed_out = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            if (
                attempt >= _RETRY_POLICY.max_attempts
                or not _is_retryable(exc)
                or (timed_out and not retry_on_timeout)
                or not _RETRY_BUDGET.take()
            ):
                raise
            await abortable_sleep(next_delay(attempt, _RETRY_POLICY))
    raise RuntimeError("unreachable")


def _balanced_object(text: str) -> str | None:
    """从首个 `{` 起做括号配平，返回完整的顶层对象；不配平返回 None。

    必须跳过字符串内部的花括号与转义引号——提示词正文里出现 JSON 片段是常态，
    用 `rfind('}')` 截取会把「对象 + 后续说明里的大括号」一并吞进来（2026-11-07 清理）。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_json(text: str) -> str:
    """从模型输出提取 JSON 主体：围栏 → 括号配平；都不成立时原样返回。

    多个围栏块时逐个尝试：模型常先给一个「分析：{}」的说明块，再给真正的 JSON 块，
    取第一个非空对象即命中（2026-11-07 清理 shortcut）。
    """
    text = text.strip()
    for match in _JSON_FENCE_RE.finditer(text):
        balanced = _balanced_object(match.group(1))
        if balanced is not None and len(balanced) > 2:  # 跳过空对象 `{}`
            return balanced
    balanced = _balanced_object(text)
    if balanced is not None:
        return balanced
    return text


def last_usage() -> dict[str, int | None] | None:
    """F-805 成本监控起建：返回最近一次结构化调用的 token 用量。

    ``cached_tokens`` 为 None 表示供应商未返回缓存命中信息——**不虚报 0**。
    """
    return _last_usage.get()


def _cached_tokens(usage: object) -> int | None:
    """读取供应商返回的缓存命中 token；无该字段返回 None。

    兼容三种形态：
    - OpenAI SDK：``usage.prompt_tokens_details.cached_tokens``；
    - openai-agents ``Usage``：``usage.input_tokens_details.cached_tokens``；
    - 原生适配器 dict：顶层 ``cached_tokens`` 或嵌套 details。
    """
    nil = object()
    details: object | None
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
        if details is None:
            value = usage.get("cached_tokens", nil)
            if value is nil:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    else:
        details = getattr(usage, "prompt_tokens_details", None) or getattr(
            usage, "input_tokens_details", None
        )
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


#: token 字段别名：OpenAI 用 prompt/completion，openai-agents Usage 用 input/output。
_USAGE_KEY_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "prompt_tokens": ("prompt_tokens", "input_tokens"),
    "completion_tokens": ("completion_tokens", "output_tokens"),
    "total_tokens": ("total_tokens",),
}


def _usage_int(usage: object, key: str) -> int:
    """取用量字段：SDK 对象走属性，原生适配器回 dict，缺字段记 0。

    2026-11-10：`agents.usage.Usage` 的字段名是 input_tokens/output_tokens，
    旧实现只读 prompt_tokens/completion_tokens，导致原生适配器明细恒为 0。
    """
    for alias in _USAGE_KEY_ALIASES.get(key, (key,)):
        value = usage.get(alias) if isinstance(usage, dict) else getattr(usage, alias, None)
        if value is not None:
            return int(value or 0)
    return 0


def _usage_of(result: object) -> object | None:
    """从 RunResult 取 token 用量。

    2026-11-14（D-06）：当前 openai-agents 的 ``RunResult`` **没有** ``usage``
    属性，用量挂在 ``raw_responses[*].usage``；旧实现 ``getattr(result, "usage")``
    恒为 None，导致真实调用 token 恒 0。保留旧路径以兼容未来/旧版本。
    """
    usage: object | None = getattr(result, "usage", None)
    if usage is not None:
        return usage
    responses = getattr(result, "raw_responses", None) or []
    if responses:
        value: object | None = getattr(responses[-1], "usage", None)
        return value
    return None


def _record_usage(usage: object | None) -> None:
    """记录一次调用的 token 用量：last（最近一次，兼容旧调用方）+ 请求级聚合。

    2026-11-10：
    - dict 形态（原生适配器）也必须取到 total——旧实现用 getattr 对 dict 恒为 0；
    - total 缺失时用 prompt+completion 兜底；
    - 所有数值钳到非负，防止供应商脏数据造成负成本。
    """
    if usage is None:
        _last_usage.set(None)
        return
    prompt = max(0, _usage_int(usage, "prompt_tokens"))
    completion = max(0, _usage_int(usage, "completion_tokens"))
    total = max(0, _usage_int(usage, "total_tokens"))
    if total == 0 and (prompt or completion):
        total = prompt + completion
    cached = _cached_tokens(usage)
    if cached is not None:
        cached = max(0, cached)
    _last_usage.set(
        {
            "total_tokens": total,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_tokens": cached,
        }
    )
    add_llm_usage(total, prompt, completion, cached)


def _build_client(key: Hashable) -> AsyncOpenAI:
    """按缓存键构造客户端；池化后同一 (model, endpoint, key) 只建一次。"""
    model, base_url, api_key = cast(tuple[str, str, str], key)
    # max_retries=0：SDK 默认重试会被外层 wait_for 一并吞掉，表现为「卡满 60s」；
    # 重试统一走本模块的 RetryBudget（A11），避免 provider × agent 相乘。
    return AsyncOpenAI(base_url=base_url, api_key=api_key or "EMPTY", max_retries=0)


#: 客户端池（G1）：LRU 4，键含端点与密钥（同一 model id 换端点必须重建）。
_CLIENTS: Final[ModelPool[AsyncOpenAI]] = ModelPool(_build_client, capacity=4)


def _ensure_client(cfg: AppConfig) -> AsyncOpenAI:
    """惰性获取 OpenAI 兼容客户端（同一 model 复用，切换模型不互相重建）。

    **刻意不调 `set_default_openai_api`**：那是进程级单例，Web 并发下按 provider
    反复设置会相互覆盖（A 请求设 responses、B 请求设 chat_completions → 随机 4xx）。
    API 形态改为**按调用注入 Model 实例**，见 :func:`build_model`。
    """
    if not cfg.llm_base_url or not cfg.llm_model:
        raise ConfigurationError(
            "LLM 未配置：需要 LLM_BASE_URL / LLM_MODEL 环境变量",
            context={
                "llm_base_url_set": bool(cfg.llm_base_url),
                "llm_model_set": bool(cfg.llm_model),
            },
        )
    client = _CLIENTS.get((cfg.llm_model, cfg.llm_base_url, cfg.llm_api_key))
    set_default_openai_client(client)
    set_tracing_disabled(True)  # 第三方 key 走 tracing 会 401
    return client


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


def _instructions(cfg: AppConfig, system: str, schema: str) -> str:
    """B18 模型族校准：按厂商把纠偏一句话插进 system；未知厂商不插（不猜）。

    无校准语句时输出与改造前逐字节一致，保证既有 prompt 测试不受影响。
    """
    note = family_note(cfg.llm_provider or "")
    head = f"{system}\n\n{note}" if note else system
    return f"{head}\n\n{JSON_STRICT_RULES}\n且必须符合如下 JSON Schema：\n{schema}"


#: 路由目的（G3）：决定统计键与账本 task_kind；decide（next_action）与 rank 同为轻活。
RoutingPurpose = Literal["probe", "rank", "generate", "summarize", "decide"]

_PURPOSE_TASK_KIND: Final[dict[str, str]] = {
    "probe": "probe",
    "rank": "rank",
    "generate": "generate",
    "summarize": "summarize",
    "decide": "rank",
}

#: 按用途的思考强度上限（2026-11-15 延迟治理）：只下调不上调，条目显式更低值优先。
#: 依据：推理型模型的 TTFT 由推理 token 长度决定，决策类短任务无需深思。
_PURPOSE_EFFORT_CAP: Final[dict[str, str]] = {
    "probe": "low",
    "rank": "low",
    "decide": "low",
    "generate": "medium",
    "summarize": "none",
}
_EFFORT_RANK: Final[dict[str, int]] = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _cfg_with_effort_cap(cfg: AppConfig, purpose: str) -> AppConfig:
    """按 purpose 给 reasoning_effort 设上限；未登记该参数或已低于上限时原样返回。"""
    cap = _PURPOSE_EFFORT_CAP.get(purpose)
    current = cfg.reasoning_effort_value()
    if cap is None or not current:
        return cfg
    if _EFFORT_RANK.get(current, len(_EFFORT_RANK)) <= _EFFORT_RANK.get(
        cap, len(_EFFORT_RANK)
    ):
        return cfg
    params = dict(cfg.llm_params or {})
    params["reasoning_effort"] = cap
    return cfg.model_copy(update={"llm_params": params})


def _candidate_cfg(cfg: AppConfig, entry: Mapping[str, Any]) -> AppConfig:
    """把注册表条目落成一个可调用配置（api_mode 空串=按 provider 默认解析）。

    2026-11-10：**按候选条目取参数**，不再继承激活条目的 effort / 窗口。
    否则主备切到别的模型时，会把激活条目的 reasoning_effort 发给一个没登记该能力的
    端点（项目记忆中的硬约束：不支持该参数的第三方端点不得下发）。

    空值→``none`` 的解析用静态能力位；动态目录给出的非空 effort 原样保留
    （写入时已校验，不因静态表缺失而丢弃）。
    """
    provider = str(entry.get("provider") or "")
    model_id = str(entry.get("model_id") or "")
    meta = model_meta_of(provider, model_id)
    allowed = meta.reasoning_efforts if meta is not None else ()
    effort = resolve_effort(str(entry.get("reasoning_effort") or ""), allowed)

    params = {
        key: value for key, value in (cfg.llm_params or {}).items() if key != "reasoning_effort"
    }
    if effort:
        params["reasoning_effort"] = effort
    window = entry.get("max_context_length")
    # 条目未显式选档时回落静态标称窗口（模型级 → 厂商级）；都没有才交给全局默认。
    # 不能直接写 0：那会让「标称 200K 但未选档」的模型被当成 1M 全局窗口。
    effective_window = (
        int(window)
        if isinstance(window, int) and window > 0
        else (max_context_length_of(provider, model_id) or 0)
    )
    return cfg.model_copy(
        update={
            "llm_model": model_id,
            "llm_provider": provider,
            "llm_base_url": str(entry.get("base_url") or ""),
            "llm_api_key": str(entry.get("api_key") or ""),
            "api_mode": str(entry.get("api_mode") or ""),
            "llm_params": params,
            "max_context_length": effective_window,
        }
    )


async def _resolve_chain(cfg: AppConfig) -> list[AppConfig]:
    """候选链（确定性，2026-11-15 用户裁定：选了什么模型就用什么模型）。

    空表或未启用多路由时返回 ``[cfg]``（现状路径，字节级行为对等）。

    启用多路由时顺序固定：激活条目（active_model_id）命中则置首；未设或未命中则
    注册表**首个可用条目**置首；其余条目按注册顺序追加为 failover。
    **不做随机探索、不做胜率排序**——主模型只由用户的显式选择决定。
    """
    entries = load_candidates()
    if not cfg.multi_model_routing or len(entries) <= 1:
        return [cfg]
    registry = read_model_registry()
    active_id = str(registry.get("active_model_id") or "") if isinstance(registry, dict) else ""
    primary_id = ""
    if active_id:
        for entry in entries:
            if active_id in (str(entry.get("id") or ""), str(entry.get("model_id") or "")):
                primary_id = str(entry.get("model_id") or "")
                break
    if not primary_id:
        primary_id = str(entries[0].get("model_id") or "")
    ordered = sorted(
        entries,
        key=lambda entry: str(entry.get("model_id") or "") != primary_id,
    )
    return [_candidate_cfg(cfg, entry) for entry in ordered]


async def _record_routing_stat(
    cfg: AppConfig, *, task_kind: str, success: bool, latency_ms: int
) -> None:
    """路由账本（G9）：旁路，失败只降级为不记账，绝不影响主调用。"""
    try:
        await SQLiteRoutingStats(cfg.db_path).record(
            model_id=cfg.llm_model,
            task_kind=task_kind,
            success=success,
            latency_ms=latency_ms,
        )
    except Exception:  # noqa: BLE001 - 账本失败不阻断调用
        logger.debug("routing.record_failed", exc_info=True)


async def _structured_once(
    cfg: AppConfig,
    output_type: type[ModelT],
    system: str,
    user: str,
    *,
    timeout: float,
    purpose: str,
    images: tuple[str, ...] = (),
) -> ModelT:
    """单候选的一次结构化调用（含纠偏重试），失败转细分错误码（M-9）。

    ``images`` 非空时走多模态消息（2026-11-14 图生图）；纠偏重试仅重发文本——
    上一轮输出已包含模型对图像的解读，重发原图只增加无谓 token。
    """
    _ensure_client(cfg)
    schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
    instructions = _instructions(cfg, system, schema)
    _emit_request_params(cfg, purpose)
    # 思考强度按用途设上限（只下调）：决策类短任务不再吃 high 的长推理延迟
    tuned = _cfg_with_effort_cap(cfg, purpose)
    agent = Agent(
        name="devprompt-llm",
        instructions=instructions,
        model=build_model(cfg),
        model_settings=ModelSettings(
            **tuned.effective_llm_params(),
            # reasoning_effort 等 ModelSettings 未建模的参数走 extra_body 真正下发
            extra_body=tuned.extra_body_params() or None,
        ),
    )
    started = time.monotonic()
    payload = _user_payload(user, images)
    # 生成阶段有推送出口时走流式（首字更早）；否则沿用阻塞式调用
    use_stream = purpose == "generate" and _GENERATION_SINK.get() is not None
    try:
        if use_stream:
            result = await _run_streamed_generate(agent, payload, timeout)
        else:
            # 生成超时不重试（2026-11-15）：重试会与兜底模板叠加成 2×超时 + 一次重跑
            result = await _run_with_retry(
                agent,
                payload,
                timeout,
                retry_on_timeout=purpose != "generate",
            )
    except Exception as exc:
        # 失败留痕（2026-11-15）：此前只能靠「trace 少一条 response」推断模型超时
        emit_error(
            "llm.error",
            purpose=purpose,
            model=cfg.llm_model,
            error=type(exc).__name__,
            timeout_s=timeout,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        # LLM 调用失败 → 细分错误码（5011~5015），供前端给精确文案（M-9）
        await _record_routing_stat(
            cfg,
            task_kind=_PURPOSE_TASK_KIND.get(purpose, "generate"),
            success=False,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise _llm_failure_error(exc, cfg, output_type) from exc
    _record_usage(_usage_of(result))
    raw = str(result.final_output)
    parsed = _parse_model(output_type, raw)
    if parsed is not None:
        await _record_routing_stat(
            cfg,
            task_kind=_PURPOSE_TASK_KIND.get(purpose, "generate"),
            success=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return parsed
    # 纠偏重试一次：把首轮输出与解析失败原因回喂，要求修正为纯 JSON
    retry_input = (
        f"{user}\n\n你上一轮输出无法解析为符合 Schema 的 JSON，原样如下：\n{raw[:2000]}\n\n"
        "请修正：只输出一个符合 Schema 的 JSON 对象，无围栏无解释。"
    )
    try:
        result2 = await asyncio.wait_for(
            Runner.run(agent, retry_input, max_turns=1), timeout=timeout
        )
    except Exception as exc:
        await _record_routing_stat(
            cfg,
            task_kind=_PURPOSE_TASK_KIND.get(purpose, "generate"),
            success=False,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise _llm_failure_error(exc, cfg, output_type) from exc
    _record_usage(_usage_of(result2))
    parsed2 = _parse_model(output_type, str(result2.final_output))
    await _record_routing_stat(
        cfg,
        task_kind=_PURPOSE_TASK_KIND.get(purpose, "generate"),
        success=parsed2 is not None,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    if parsed2 is None:
        raise GenerationError(
            "LLM 两次输出均无法解析为约定 JSON 结构",
            code=4003,
            context={"model": cfg.llm_model, "output_type": output_type.__name__},
        )
    return parsed2


def _assert_request_budget(
    cfg: AppConfig, system: str, user: str, *, purpose: str = "generate"
) -> None:
    """A7 请求级预算断言：system+user+预留输出必须装进窗口，不足即抛。

    `RequestBudgetError` 被 `is_context_overflow` 识别，service 层的
    `with_overflow_retry` 会压缩一次上下文后重发（A7 与 A8 同一闭环）。

    2026-11-10：窗口取 ``cfg.runtime_window()``（条目档位优先）。
    生成路径保留原始 `RequestBudgetError` 供 service 压缩重发；其它路径转 3003，
    避免把「所选窗口太小」暴露成未分类的 500。
    """
    max_output = int(cfg.effective_llm_params().get("max_tokens") or 0)
    window = cfg.runtime_window()
    try:
        ensure_request_fits(
            estimate_tokens(f"{system}\n\n{user}"),
            request_budget(window, max_output),
        )
    except RequestBudgetError as exc:
        if purpose == "generate":
            raise
        raise DevPromptError(
            f"所选上下文窗口不足（{window} token）：{exc}",
            code=registered(3003),
            context={"window": window, "purpose": purpose},
        ) from exc


def _emit_request_params(cfg: AppConfig, purpose: str) -> None:
    """记录本次请求的模型参数（不含 prompt / 密钥，MUST-19）。

    供全链路验证与线上归因：能看到「用户选了 high、实际下发的是 high」，
    而不是只能相信 UI。
    """
    emit(
        "llm.request_params",
        model=cfg.llm_model,
        provider=cfg.llm_provider,
        api_mode=resolve_api_mode(cfg.llm_provider or "", cfg.api_mode or ""),
        purpose=purpose,
        reasoning_effort=cfg.reasoning_effort_value(),
        context_window=cfg.runtime_window(),
    )


async def chat_structured(
    cfg: AppConfig,
    output_type: type[ModelT],
    system: str,
    user: str,
    *,
    timeout: float | None = None,
    purpose: RoutingPurpose = "generate",
    images: tuple[str, ...] = (),
) -> ModelT:
    """单次结构化调用（多模型路由 + 主备，G2–G6/G9）。

    timeout 缺省取 cfg.llm_timeout（F-604 可配置；小证据探针等调用方可显式传短超时）；
    温度/max_tokens 经 ModelSettings 下发（未设则不下发，走供应商默认）。
    F-004 适配：prompt 注入 JSON Schema，本地解析 + pydantic 校验 + 一次纠偏重试——
    不依赖供应商 response_format（实测 DeepSeek 400: response_format type unavailable）。

    路由：候选 ≤1 或未开 `multi_model_routing` 时链上只有当前配置（行为对等）；
    可降级失败（超时/限流/上游错误）按链顺次切换，额度/鉴权类直接抛。
    """
    _assert_request_budget(cfg, system, user, purpose=purpose)
    effective_timeout = timeout if timeout is not None else cfg.llm_timeout
    chain = await _resolve_chain(cfg)
    last_error: DevPromptError | None = None
    for index, candidate in enumerate(chain):
        # 候选级预算：主备模型的窗口可能不同，不能只按激活条目判一次。
        _assert_request_budget(candidate, system, user, purpose=purpose)
        try:
            return await _structured_once(
                candidate,
                output_type,
                system,
                user,
                timeout=effective_timeout,
                purpose=purpose,
                images=images,
            )
        except DevPromptError as exc:
            last_error = exc
            if exc.code not in _FAILOVER_CODES or index == len(chain) - 1:
                raise
            logger.warning(
                "llm.failover",
                extra={"model": candidate.llm_model, "code": exc.code, "purpose": purpose},
            )
    assert last_error is not None  # 链恒非空，最后一个候选要么成功要么已 raise
    raise last_error


def _parse_model(output_type: type[ModelT], raw: str) -> ModelT | None:
    """解析并校验模型输出；失败返回 None（由调用方决定重试或报错）。"""
    try:
        return output_type.model_validate_json(_extract_json(raw))
    except ValidationError:
        return None


class LLMGenerator:
    """GeneratePort 的 LLM 实现（F-301：generate_single 为唯一生成入口）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def generate_single(
        self,
        ctx: GenerationContext,
        locale: Locale = DEFAULT_LOCALE,
        *,
        fallback: bool = False,
    ) -> VariantDraft:
        """单套生成（2026-11-11）：常规恒用 B 标准版，``fallback`` 时才用 A 保守版。"""
        from devprompt_ai.domain.generate.templates import template_for
        from devprompt_ai.harness.guardrails import validate_variant

        tpl = template_for(fallback)
        # 生成类调用输出长（完整方案正文）：timeout 缺省即 cfg.llm_timeout（F-604，默认 60s；
        # 10s 会截断真实生成——4H 端到端实测）
        # 兜底版只写意图与剩余风险（≤几百字），收紧 max_tokens 换取更快返回（2026-11-15）
        cfg = (
            self._cfg.model_copy(update={"llm_max_tokens": 1500})
            if fallback and self._cfg.llm_max_tokens is None
            else self._cfg
        )
        draft = await chat_structured(
            cfg,
            VariantDraft,
            tpl.system(locale, ctx.domain_id),
            tpl.build_user(ctx, locale),
            timeout=cfg.llm_generate_timeout,
            purpose="generate",
            images=ctx.images,
        )
        validate_variant(draft)
        # 兜底标记由模板选择单向决定，不接受模型自报（避免模型输出覆盖）。
        draft.fallback = fallback
        return draft

    async def answer(self, ctx: GenerationContext, locale: Locale = DEFAULT_LOCALE) -> str:
        """纯回答（2026-11-05）：一次结构化调用，只取正文。

        与 generate_single 的唯一差别是输出模型——``ReplyOutput`` 没有
        title/changes/claims/fallback 字段，从类型上就不可能是方案。
        """
        from devprompt_ai.domain.generate.ports import ReplyOutput
        from devprompt_ai.domain.generate.templates import reply as reply_tpl

        out = await chat_structured(
            self._cfg,
            ReplyOutput,
            reply_tpl.system_text(locale),
            reply_tpl.build_user(ctx, locale),
            timeout=self._cfg.llm_generate_timeout,
            purpose="generate",
        )
        return out.text


#: LLM 调用失败场景 → 错误码（用户 2026-10-16 裁定：细分 5 个码，前端给精确文案）。
#: 5012 与 3004 的区别：3004 是决策阶段限流，本表是生成阶段（chat_structured）限流。
_LLM_FAILURE_CODES: Final[dict[str, int]] = {
    "timeout": registered(5011),
    "rate_limit": registered(5012),
    "insufficient_quota": registered(5013),
    "invalid_api_key": registered(5014),
    "upstream_error": registered(5015),
}

#: 允许主备降级的失败码：超时/限流/上游错误/余额不足。
#: 余额不足（5013）也降级：多模型注册表里的条目可能分属不同账户，
#: 单账户余额耗尽时链上其它模型仍可用（2026-11-12 实测连续 3 次因此失败）。
#: 鉴权失败（5014）不降级——同一份密钥填错，换模型救不了。
_FAILOVER_CODES: Final[frozenset[int]] = frozenset(
    code
    for scenario, code in _LLM_FAILURE_CODES.items()
    if scenario in {"timeout", "rate_limit", "upstream_error", "insufficient_quota"}
)

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


async def _tools_once(
    cfg: AppConfig, system: str, user: str, *, timeout: float, purpose: str
) -> ToolChatResult:
    """单候选的一次带工具调用（探针专用路径）。

    2026-11-10：**补齐模型参数**——此前只传 ``tool_choice``，导致思考强度与采样参数
    在探针路径被静默丢弃（与本轮其它调用行为不一致）。
    """
    model = build_model(cfg)
    _emit_request_params(cfg, purpose)
    tuned = _cfg_with_effort_cap(cfg, purpose)
    settings = ModelSettings(
        tool_choice="auto",
        **tuned.effective_llm_params(),
        extra_body=tuned.extra_body_params() or None,
    )
    started = time.monotonic()
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
            timeout=timeout,
        )
    except Exception as exc:
        await _record_routing_stat(
            cfg,
            task_kind=_PURPOSE_TASK_KIND.get(purpose, "probe"),
            success=False,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise _llm_failure_error(exc, cfg, ToolChatResult) from exc

    _record_usage(getattr(response, "usage", None))
    await _record_routing_stat(
        cfg,
        task_kind=_PURPOSE_TASK_KIND.get(purpose, "probe"),
        success=True,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    tool_call = _first_function_call(list(response.output))
    if tool_call is not None:
        return ToolChatResult(tool_call=tool_call)
    return ToolChatResult(text=_text_of(response.output))


async def chat_with_tools(
    cfg: AppConfig,
    system: str,
    user: str,
    *,
    timeout: float | None = None,
    purpose: RoutingPurpose = "probe",
    model_id: str = "",
) -> ToolChatResult:
    """单次带工具调用：模型可回 function_call（AskUserQuestion），否则回文本。

    刻意**不用 Runner**：``Runner.run(max_turns=1)`` 在模型发起工具调用时会自动执行
    工具并继续，用满轮数只会抛 ``MaxTurnsExceeded``，拿不到稳定的 call 参数。
    这里直接调 ``Model.get_response``，工具不会被真正执行（``on_invoke_tool`` 是空桩）。

    四种 provider 都能传 tools 并解析 function_call；但 anthropic/gemini 原生适配器
    不支持回喂 ``function_call_output``，因此答案不通过 tool result 回传，而是由调用方
    重建 prompt 携带「已答问题 + 答案」（见 decision/fallback.py）。

    路由与主备语义同 :func:`chat_structured`。
    """
    _assert_request_budget(cfg, system, user, purpose=purpose)
    effective_timeout = timeout if timeout is not None else cfg.llm_timeout
    chain = await _resolve_chain(cfg)
    last_error: DevPromptError | None = None
    for index, candidate in enumerate(chain):
        _assert_request_budget(candidate, system, user, purpose=purpose)
        try:
            return await _tools_once(
                candidate, system, user, timeout=effective_timeout, purpose=purpose
            )
        except DevPromptError as exc:
            last_error = exc
            if exc.code not in _FAILOVER_CODES or index == len(chain) - 1:
                raise
            logger.warning(
                "llm.failover",
                extra={"model": candidate.llm_model, "code": exc.code, "purpose": purpose},
            )
    assert last_error is not None
    raise last_error
