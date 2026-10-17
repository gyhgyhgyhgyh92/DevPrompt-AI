"""文本模型的能力元数据与参数定义（纯领域知识，零 I/O，MUST-06）。

迁自 prompt-optimizer `packages/core/src/services/model/`，仅保留**文本模型**部分
（图像/多模态适配器按裁定 D4 全部排除）。本土化要点：

- **参数定义不来自适配器**（裁定 D1）：本项目统一走 OpenAI 兼容协议，无适配器层，
  故定义改为按 provider 分组的静态表 `PROVIDER_SPECS`。provider 专属差异用表项
  携带的 `drop_params` / `force_params` 表达，清洗逻辑退化为「查表 → 剔除/覆盖」，
  **代码中零 `if provider == ...` 分支**——新增 provider 只改数据不改代码。
- **不引入内置模型目录**（裁定 D4）：`model_id` 由用户手填，未知厂商走保守默认能力，
  **不抛错**。
- **保持单 active**（裁定 D2）：本模块不涉及启用/停用语义，只描述「这个模型能做什么」。

参数是否真正下发，由 `config.AppConfig.effective_llm_params()` 决定；本模块只负责
「定义合法值域」与「校验用户输入」，不做下发决策（MUST-08：判定不落在前端/工具层）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

#: 参数类型。`string-array` 用于 stop 这类需要 JSON 序列化的多值参数。
ParameterType = Literal["number", "integer", "boolean", "string", "string-array"]

#: API 形态（2026-09-17 多供应商扩展）。
#:
#: - `chat_completions`：OpenAI Chat Completions，**绝大多数第三方厂商只实现这一种**
#: - `responses`：OpenAI Responses API，仅 OpenAI 官方端点完整支持
#: - `anthropic_messages` / `gemini_generate_content`：原生形态，走 `harness/adapters/`
#:
#: 为什么默认不是 `responses`：本项目早年统一 chat_completions 正是因为「第三方基本不
#: 支持 Responses API」（技术栈 §4.5），该结论至今成立，故除 openai 外全部默认 chat。
ApiMode = Literal["chat_completions", "responses", "anthropic_messages", "gemini_generate_content"]

#: 全部 API 形态（供契约与前端下拉）。
ALL_API_MODES: Final[tuple[ApiMode, ...]] = (
    "chat_completions",
    "responses",
    "anthropic_messages",
    "gemini_generate_content",
)

#: 参数是否会被 `ModelSettings` 原生下发（其余需 `extra_body`，本轮不接线）。
#: 依据：openai-agents `ModelSettings` 的字段列表实测。
NATIVE_PARAMETERS: Final[frozenset[str]] = frozenset(
    {"temperature", "top_p", "frequency_penalty", "presence_penalty", "max_tokens"}
)

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """单个可调参数的完整定义（对齐源项目 `UnifiedParameterDefinition`）。

    字段命名从camelCase 转为 snake_case 以符合 MUST-17；语义一一对应。
    """

    name: str
    type: ParameterType
    label: str
    description: str = ""
    default_value: Any | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    allowed_values: tuple[str, ...] = ()
    unit: str = ""
    #: 该参数在哪些 API 形态下真正生效。默认全形态——绝大多数参数无形态差异。
    #: `frequency_penalty` / `presence_penalty` 是已知例外：openai-agents 在 responses
    #: 模式的 payload 中不含这两个键（实测 openai_responses.py:1039-1056），故仅在
    #: `chat_completions` 下标为原生。**不全局移除**——DeepSeek 等走 chat 的厂商仍支持。
    native_modes: frozenset[ApiMode] = frozenset(ALL_API_MODES)

    @property
    def is_native(self) -> bool:
        """是否会被 `ModelSettings` 原生下发（本轮只有原生参数真正生效）。

        注意：这是**与 api_mode 无关**的静态判定（该参数名是否属于 ModelSettings）。
        要判断「当前 provider 的 api_mode 下是否生效」，用
        :func:`is_native_in_mode`——两者结论可能不同（penalty 即如此）。
        """
        return self.name in NATIVE_PARAMETERS

    def is_native_in_mode(self, api_mode: ApiMode) -> bool:
        """该参数在指定 API 形态下是否真正生效。"""
        return self.is_native and api_mode in self.native_modes

    def to_dict(self) -> dict[str, Any]:
        """可序列化投影（供契约与前端消费；`domain/` 不含 HTTP 概念，此为纯数据导出）。"""
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "default_value": self.default_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "step": self.step,
            "allowed_values": list(self.allowed_values),
            "unit": self.unit,
            "is_native": self.is_native,
            "native_modes": sorted(self.native_modes),
        }


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """模型能力标记（对齐源项目 `ModelCapabilities`，仅文本模型相关三项）。"""

    supports_tools: bool
    supports_reasoning: bool
    max_context_length: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supports_tools": self.supports_tools,
            "supports_reasoning": self.supports_reasoning,
            "max_context_length": self.max_context_length,
        }


def max_context_length_of(provider: str, model_id: str = "") -> int | None:
    """该 provider（及模型）的上下文窗口上限；未知返回 ``None``。

    :param provider: provider key（大小写不敏感）
    :param model_id: 模型 id——预留用于按模型的细分覆盖，当前按 provider 级取值
    """
    spec = PROVIDER_SPECS.get(resolve_provider_key(provider))
    if spec is None:
        return None
    return spec.max_context_length


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """一个厂商的参数与约束定义（裁定 D1：静态表，非适配器）。

    `drop_params` / `force_params` 是 provider 专属知识的唯一载体——源项目把这些写在
    `if (adapterId === 'anthropic')` 分支里，本项目改为数据，从而保持清洗逻辑零分支。

    多供应商扩展字段（2026-09-17）：

    - `api_mode`：默认 API 形态。`chat_completions` 为 OpenAI 兼容形态（绝大多数第三方
      厂商只实现这一种）；`responses` 仅 OpenAI 官方；`anthropic_messages` /
      `gemini_generate_content` 为原生形态（见 `harness/adapters/`）。
    - `supported_api_modes`：该 provider 允许的模式集，控制设置中心的下拉可选值。
    - `adapter_kind`：走哪个 adapter 构造器（`harness/adapters/registry.py`）。
    - `base_url`：官方端点。**查证不到的留空字符串**，由 UI 提示用户自行查询文档填写
      （2026-09-17 逐个 web_search 核实，不得凭印象书写）。
    - `needs_key`：本地推理引擎（ollama/vllm/lmstudio）不校验 key 非空。
    - `quirks`：逐家已知怪癖，纯描述性文本，供 UI 展示与后续维护参考。
    """

    key: str
    label: str
    aliases: frozenset[str] = frozenset()
    parameters: tuple[ParameterDefinition, ...] = ()
    drop_params: frozenset[str] = frozenset()
    force_params: Mapping[str, Any] = field(default_factory=dict)
    supports_tools: bool = True
    supports_reasoning: bool = False
    max_context_length: int | None = None
    # ---- 多供应商扩展 ----
    api_mode: ApiMode = "chat_completions"
    supported_api_modes: frozenset[ApiMode] = frozenset({"chat_completions"})
    adapter_kind: str = "openai_compat"
    base_url: str = ""
    needs_key: bool = True
    quirks: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "api_mode": self.api_mode,
            "supported_api_modes": sorted(self.supported_api_modes),
            "adapter_kind": self.adapter_kind,
            "base_url": self.base_url,
            "needs_key": self.needs_key,
            "supports_tools": self.supports_tools,
            "supports_reasoning": self.supports_reasoning,
            "max_context_length": self.max_context_length,
            "parameters": [p.to_dict() for p in self.parameters],
        }


# ---------------------------------------------------------------------------
# 安全：危险键名黑名单（迁自源项目 parameter-schema.ts:10-33，共22 条）
# ---------------------------------------------------------------------------

#: 命中任一子串即拒绝。Python 侧虽无原型链，但键名会经 JSON 落到下游，
#: 仍须防注入（如 `__proto__` 污染前端对象、`authorization` 越权下发）。
DANGEROUS_PARAM_KEY_PATTERNS: Final[tuple[str, ...]] = (
    "__proto__",
    "constructor",
    "prototype",
    "eval",
    "exec",
    "script",
    "process",
    "child_process",
    "function",
    "code",
    "apikey",
    "api_key",
    "secret",
    "password",
    "credential",
    "authorization",
    "bearer",
    "token",
    "baseurl",
    "base_url",
    "endpoint",
    "url",
)

#: 合法键名字符集（源项目 `^[A-Za-z0-9._\-:/]+$`）。
_SAFE_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._\-:/]+$")


def is_safe_custom_key(key: str) -> bool:
    """键名是否安全：非空 + 字符集白名单 + 不含任何危险子串（大小写不敏感）。

    迁自源项目 `isSafeCustomKey`（parameter-schema.ts:121-135）。
    """
    if not isinstance(key, str):
        return False
    candidate = key.strip()
    if not candidate or not _SAFE_KEY_PATTERN.match(candidate):
        return False
    lowered = candidate.lower()
    return not any(pattern in lowered for pattern in DANGEROUS_PARAM_KEY_PATTERNS)


def is_value_empty(value: Any) -> bool:
    """值是否应视为「未设置」（迁自源项目 `isValueEmpty`，:87-101）。

    空值统一转成「不下发」而非下发空串/零值——后者会让部分供应商报参数错误。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple):
        return len(value) == 0
    return False


# ---------------------------------------------------------------------------
# 参数定义（各厂商取值范围不同的同名参数按 provider 区分）
# ---------------------------------------------------------------------------


#: 采样类参数的公共定义。temperature 在 OpenAI 系是 0~2、部分国产厂商是 0~1——
#: 源项目正是因此把范围下沉到 provider 分组，本项目沿用该做法。
def _sampling(temperature_max: float) -> tuple[ParameterDefinition, ...]:
    return (
        ParameterDefinition(
            name="temperature",
            type="number",
            label="随机性",
            description="越高输出越发散；事实抽取类任务建议偏低",
            min_value=0.0,
            max_value=temperature_max,
            step=0.1,
            default_value=0.3,
        ),
        ParameterDefinition(
            name="max_tokens",
            type="integer",
            label="最大输出 token",
            description="C 档三套方案输出较长，建议不低于 2048",
            min_value=1,
            max_value=131072,
            step=1,
            unit="token",
        ),
        ParameterDefinition(
            name="top_p",
            type="number",
            label="核采样",
            description="与随机性二选一调整即可，同时改会互相干扰",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
        ),
        ParameterDefinition(
            name="frequency_penalty",
            type="number",
            label="频率惩罚",
            description="越高越抑制重复用词；仅 Chat Completions 形态生效",
            min_value=-2.0,
            max_value=2.0,
            step=0.1,
            native_modes=frozenset({"chat_completions"}),
        ),
        ParameterDefinition(
            name="presence_penalty",
            type="number",
            label="存在惩罚",
            description="越高越鼓励引入新话题；仅 Chat Completions 形态生效",
            min_value=-2.0,
            max_value=2.0,
            step=0.1,
            native_modes=frozenset({"chat_completions"}),
        ),
    )


#: 推理类厂商额外支持 effort 档位（本轮登记但不下发：需 `extra_body` 接线）。
_REASONING_PARAM: Final[ParameterDefinition] = ParameterDefinition(
    name="reasoning_effort",
    type="string",
    label="推理强度",
    description="仅推理模型有效；非推理模型下发会报错",
    allowed_values=("low", "medium", "high"),
    default_value="high",
)

#: provider 定义表。**这是 provider 专属知识的唯一载体**——新增厂商只改本表，不改代码。
#:
#: `drop_params` / `force_params` 逐条对应源项目 `manager.ts:272-298` 的 if 分支：
#: anthropic 删 temperature/top_p/top_k/thinking_budget_tokens 并强制 effort=high；
#: gemini 删 temperature/topP/topK/candidateCount/thinkingBudget；
#: grok 把 reasoning_effort=none 改为 high；deepseek 对reasoner 模型开thinking。
#:
#: 多供应商扩展（2026-09-17）：新增 `api_mode` / `supported_api_modes` / `adapter_kind` /
#: `base_url` / `needs_key` / `quirks` 六字段。**全部 base_url 均经 web_search 逐个核实**；
#: 空串表示查证后仍无可靠公开端点，UI 会提示用户自行查询文档填写。
#: 除 openai 外全部默认 `chat_completions`——第三方厂商基本只实现这一种（技术栈 §4.5）。

#: 国内 OpenAI 兼容厂商的公共参数集。
_DOMESTIC_PARAMS: Final[tuple[ParameterDefinition, ...]] = _sampling(2.0)

#: 支持推理的厂商追加 effort 档位。
_REASONING_MODELS: Final[tuple[ParameterDefinition, ...]] = (*_sampling(2.0), _REASONING_PARAM)

PROVIDER_SPECS: Final[dict[str, ProviderSpec]] = {
    # ---- 国外 ----
    "openai": ProviderSpec(
        key="openai",
        label="OpenAI",
        aliases=frozenset({"openai"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=200000,
        # 唯一默认 responses 的 provider：官方端点完整支持
        api_mode="responses",
        supported_api_modes=frozenset({"responses", "chat_completions"}),
        adapter_kind="openai_responses",
        base_url="https://api.openai.com/v1",
    ),
    "anthropic": ProviderSpec(
        key="anthropic",
        label="Anthropic",
        aliases=frozenset({"anthropic", "claude"}),
        parameters=_sampling(2.0),
        drop_params=frozenset({"temperature", "top_p"}),
        force_params={"reasoning_effort": "high"},
        supports_reasoning=True,
        max_context_length=200000,
        api_mode="anthropic_messages",
        supported_api_modes=frozenset({"anthropic_messages", "chat_completions"}),
        adapter_kind="anthropic_native",
        base_url="https://api.anthropic.com",
        quirks="原生 Messages 用 x-api-key 头；强制 max_tokens；temperature/top_p 无效",
    ),
    "gemini": ProviderSpec(
        key="gemini",
        label="Google Gemini",
        aliases=frozenset({"gemini", "google"}),
        parameters=_sampling(2.0),
        drop_params=frozenset({"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        supports_reasoning=True,
        max_context_length=1000000,
        api_mode="gemini_generate_content",
        supported_api_modes=frozenset({"gemini_generate_content", "chat_completions"}),
        adapter_kind="gemini_native",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        quirks="OpenAI 兼容层有并发与配额限制；长上下文按梯度计费",
    ),
    "grok": ProviderSpec(
        key="grok",
        label="xAI Grok",
        aliases=frozenset({"grok", "xai"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=131072,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.x.ai/v1",
    ),
    # ---- 国内主力 ----
    "deepseek": ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        aliases=frozenset({"deepseek"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=64000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.deepseek.com",
        quirks="reasoner 模型需开 thinking；V3 系不支持 reasoning_effort",
    ),
    "dashscope": ProviderSpec(
        key="dashscope",
        label="阿里通义（百炼）",
        aliases=frozenset({"dashscope", "qwen", "tongyi", "阿里"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=131072,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        quirks="需用 compatible-mode 路径；Coding Plan 套餐有专属 base_url",
    ),
    "zhipu": ProviderSpec(
        key="zhipu",
        label="智谱 GLM",
        aliases=frozenset({"zhipu", "glm", "智谱"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        quirks="base_url 末尾斜杠不可省略",
    ),
    "moonshot": ProviderSpec(
        key="moonshot",
        label="月之暗面 Kimi",
        aliases=frozenset({"moonshot", "kimi"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=131072,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.moonshot.cn/v1",
    ),
    "volcengine": ProviderSpec(
        key="volcengine",
        label="火山方舟（豆包）",
        aliases=frozenset({"volcengine", "doubao", "ark", "豆包"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=131072,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        quirks="模型 id 需带推理接入点 ID（ep-xxx），非裸模型名",
    ),
    "qianfan": ProviderSpec(
        key="qianfan",
        label="百度千帆（文心）",
        aliases=frozenset({"qianfan", "ernie", "文心", "百度"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=131072,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://qianfan.baidubce.com/v2",
        quirks="v2 与旧版地址不兼容；部分模型需 IAM 签名而非 Bearer",
    ),
    "hunyuan": ProviderSpec(
        key="hunyuan",
        label="腾讯混元",
        aliases=frozenset({"hunyuan", "混元", "腾讯"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
    ),
    "spark": ProviderSpec(
        key="spark",
        label="讯飞星火",
        aliases=frozenset({"spark", "xfyun", "讯飞"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://spark-api-open.xf-yun.com/v2",
        quirks="不同模型版本 base_url 路径不同（/v2、/x2）",
    ),
    "minimax": ProviderSpec(
        key="minimax",
        label="MiniMax",
        aliases=frozenset({"minimax"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=1000000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.minimaxi.com/v1",
        quirks="中国大陆（minimaxi.com）与海外（minimax.io）Key 与地址不可混用",
    ),
    "stepfun": ProviderSpec(
        key="stepfun",
        label="阶跃星辰",
        aliases=frozenset({"stepfun", "阶跃"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.stepfun.com/v1",
    ),
    # ---- 国内长尾 ----
    "baichuan": ProviderSpec(
        key="baichuan",
        label="百川智能",
        aliases=frozenset({"baichuan", "百川"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.baichuan-ai.com",
    ),
    "yi": ProviderSpec(
        key="yi",
        label="零一万物",
        aliases=frozenset({"yi", "01.ai", "零一"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=200000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        # 查证后仍无可靠公开端点（2026-09-17），留空 + UI 提示自行查询
        base_url="",
    ),
    "sensetime": ProviderSpec(
        key="sensetime",
        label="商汤（商量）",
        aliases=frozenset({"sensetime", "商汤", "sensecore"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        # 有兼容模式但 base_url 需登录控制台获取（2026-09-17），留空
        base_url="",
    ),
    "xiaomi-mimo": ProviderSpec(
        key="xiaomi-mimo",
        label="小米 MiMo",
        aliases=frozenset({"xiaomi-mimo", "mimo", "小米"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        # 仅找到临时测试域名，非官方稳定端点（2026-09-17），留空
        base_url="",
    ),
    # ---- 聚合平台 ----
    "siliconflow": ProviderSpec(
        key="siliconflow",
        label="硅基流动",
        aliases=frozenset({"siliconflow", "硅基"}),
        parameters=_REASONING_MODELS,
        supports_reasoning=True,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.siliconflow.cn/v1",
        quirks="一个 Key 调用多家模型，模型 id 形如 厂商/模型名",
    ),
    "modelscope": ProviderSpec(
        key="modelscope",
        label="魔搭 ModelScope",
        aliases=frozenset({"modelscope", "魔搭"}),
        parameters=_DOMESTIC_PARAMS,
        supports_reasoning=False,
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api-inference.modelscope.cn/v1",
        quirks="免费额度限频率；模型 id 形如 厂商/模型名",
    ),
    # ---- 自定义 / 泛称 ----
    "custom": ProviderSpec(
        key="custom",
        label="自定义",
        aliases=frozenset({"custom", "自定义"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions", "responses"}),
        adapter_kind="openai_compat",
        base_url="",
    ),
    "openai_compatible": ProviderSpec(
        key="openai_compatible",
        label="OpenAI 兼容（通用）",
        aliases=frozenset({"openai-compatible", "兼容"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions", "responses"}),
        adapter_kind="openai_compat",
        base_url="",
    ),
    # ---- 本地推理引擎（不校验 key）----
    "ollama": ProviderSpec(
        key="ollama",
        label="Ollama（本地）",
        aliases=frozenset({"ollama"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="http://localhost:11434/v1",
        needs_key=False,
        quirks="api_key 填任意非空占位值；工具调用支持取决于具体模型",
    ),
    "vllm": ProviderSpec(
        key="vllm",
        label="vLLM（本地）",
        aliases=frozenset({"vllm"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="http://localhost:8000/v1",
        needs_key=False,
        quirks="需 --enable-auto-tool-choice 才支持函数调用",
    ),
    "lmstudio": ProviderSpec(
        key="lmstudio",
        label="LM Studio（本地）",
        aliases=frozenset({"lmstudio", "lm-studio"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="http://localhost:1234/v1",
        needs_key=False,
    ),
}

#: 未登记厂商的兜底：给出中性参数集 + 保守能力，**不抛错**（裁定 D4：不引内置目录）。
_FALLBACK_PROVIDER_KEY: Final[str] = "openai_compatible"

#: 别名 → 规范 provider key（大小写不敏感）。
_ALIAS_INDEX: Final[dict[str, str]] = {
    alias.lower(): spec.key for spec in PROVIDER_SPECS.values() for alias in spec.aliases
}
_ALIAS_INDEX.update({key: key for key in PROVIDER_SPECS})

# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def resolve_provider_key(provider: str) -> str:
    """把用户填的厂商名解析为规范 key；未登记则回落通用兼容档，**不抛错**。"""
    candidate = (provider or "").strip().lower()
    return _ALIAS_INDEX.get(candidate, _FALLBACK_PROVIDER_KEY)


def resolve_capabilities(provider: str, model_id: str = "") -> ModelCapabilities:
    """解析模型能力。未知厂商走保守默认；未登记的 model_id 不影响厂商级能力。"""
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    return ModelCapabilities(
        supports_tools=spec.supports_tools,
        supports_reasoning=spec.supports_reasoning,
        max_context_length=spec.max_context_length,
    )


def provider_parameters(provider: str) -> tuple[ParameterDefinition, ...]:
    """返回该厂商的参数定义（前端据此渲染编辑器）。"""
    return PROVIDER_SPECS[resolve_provider_key(provider)].parameters


def apply_provider_constraints(provider: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """按 provider 约束清洗参数：剔除 `drop_params`、套用 `force_params`。

    这是源项目 `manager.ts:272-298` 四个 if 分支的**数据化等价物**——清洗逻辑本身
    零分支，故不需要适配器层（裁定 D1）。

    另外把空值（None / 空串 / 空数组）统一剔除，理由见 :func:`is_value_empty`。
    """
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    cleaned = {
        key: value
        for key, value in overrides.items()
        if not is_value_empty(value) and key not in spec.drop_params
    }
    for key, value in spec.force_params.items():
        cleaned[key] = value
    return cleaned


def _check_one(param: ParameterDefinition, value: Any) -> list[str]:
    """校验单个值，返回问题描述列表（空 = 通过）。"""
    expected = param.type
    if expected == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return [f"{param.label}：应为数值"]
        if param.min_value is not None and value < param.min_value:
            return [f"{param.label}：不能小于 {param.min_value}"]
        if param.max_value is not None and value > param.max_value:
            return [f"{param.label}：不能大于 {param.max_value}"]
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{param.label}：应为整数"]
        if param.min_value is not None and value < param.min_value:
            return [f"{param.label}：不能小于 {param.min_value}"]
        if param.max_value is not None and value > param.max_value:
            return [f"{param.label}：不能大于 {param.max_value}"]
    elif expected == "boolean":
        if not isinstance(value, bool):
            return [f"{param.label}：应为开关值"]
    elif expected == "string":
        if not isinstance(value, str):
            return [f"{param.label}：应为文本"]
        if param.allowed_values and value not in param.allowed_values:
            allowed = " / ".join(param.allowed_values)
            return [f"{param.label}：只能是 {allowed}"]
    elif expected == "string-array":
        if isinstance(value, str) or not isinstance(value, list):
            return [f"{param.label}：应为文本列表"]
        if not all(isinstance(item, str) for item in value):
            return [f"{param.label}：列表项须全为文本"]
    return []


def filter_safe_overrides(provider: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """过滤出「可安全下发」的参数：已登记参数 + 键名安全的未登记参数。

    **已登记参数必须绕过黑名单**——黑名单含 `token` 子串，会误伤 `max_tokens`
    这类完全合法的登记参数名。该规则集中在此函数，`validate_overrides` 与
    `normalize_overrides` 共用，避免同一缺陷在两处各犯一次。
    """
    defined = {p.name for p in PROVIDER_SPECS[resolve_provider_key(provider)].parameters}
    return {
        str(key): value
        for key, value in overrides.items()
        if str(key) in defined or is_safe_custom_key(str(key))
    }


def model_specs_projection() -> dict[str, list[dict[str, Any]]]:
    """全部 provider 的参数定义投影（provider key → 定义数组）。

    供 `GET /settings` 的 `model_specs` 段下发，前端据此渲染参数编辑器——
    **后端不下发「业务判定」，只下发定义**，控件与校验结论均由此处数据驱动。
    """
    return {
        key: [param.to_dict() for param in spec.parameters] for key, spec in PROVIDER_SPECS.items()
    }


def resolve_api_mode(provider: str, override: str = "") -> ApiMode:
    """解析该用哪种 API 形态。

    优先级：**显式条目覆盖 > provider 默认**。未登记的覆盖值回落 provider 默认
    （保守，不抛错——用户从旧数据读到的历史值可能是已下线的模式）。

    :param provider: 厂商名（用户填的，走别名解析）
    :param override: 条目上的 `api_mode` 覆盖值，空串表示未设置
    """
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    candidate = (override or "").strip()
    if candidate and candidate in spec.supported_api_modes:
        for mode in ALL_API_MODES:
            if mode == candidate:
                return mode
    return spec.api_mode


def is_mode_supported(provider: str, api_mode: str) -> bool:
    """该 provider 是否支持指定 API 形态（供设置中心限制下拉可选值）。"""
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    return api_mode in spec.supported_api_modes


def providers_projection() -> list[dict[str, Any]]:
    """provider 目录投影（供 `GET /settings` 的 `providers` 段）。

    前端据此渲染 provider 下拉与动态表单：`base_url` 为空表示**官方端点未登记**
    （逐个查证不到时如实留空，由 UI 提示用户自行查询文档填写——不得编造端点）；
    `supported_api_modes` 限制 api_mode 下拉的可选值。

    字段与契约 `ProviderDirectoryEntry` 一一对应（**刻意不复用 `spec.to_dict()`**：
    后者含 `parameters` / `adapter_kind` 等内部字段，且用 `key` 而非契约的 `id`）。
    """
    return [
        {
            "id": key,
            "label": spec.label,
            "base_url": spec.base_url,
            "needs_key": spec.needs_key,
            "default_api_mode": spec.api_mode,
            "supported_api_modes": sorted(spec.supported_api_modes),
            "max_context_length": spec.max_context_length,
            "supports_reasoning": spec.supports_reasoning,
            "quirks": spec.quirks,
        }
        for key, spec in PROVIDER_SPECS.items()
    ]


def validate_overrides(provider: str, overrides: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """校验参数覆盖值，返回 ``(错误列表, 警告列表)``。

    - **错误**：危险键名、类型不符、超出范围、枚举不匹配 —— 调用方应整单拒绝；
    - **警告**：未在该厂商定义表中登记的参数 —— 允许透传（各厂商参数差异大，硬拦会误伤），
      但要告知用户「可能不会生效」。

    语义对齐源项目 `validateOverrides`（parameter-utils.ts:226-437），其中
    `allowUnknown=true` 对应本实现把未登记参数降级为警告而非错误。
    """
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    defined = {param.name: param for param in spec.parameters}
    errors: list[str] = []
    warnings: list[str] = []

    for key, value in overrides.items():
        if key in spec.drop_params:
            # 即便参数在定义表里（如 anthropic 的 temperature），下发前也会被剔除——
            # 必须告知用户「设了不生效」，否则他会以为参数已按预期调整。
            warnings.append(f"{key}：{spec.label} 不支持该参数，保存后不会生效")
            continue
        param = defined.get(key)
        if param is not None:
            # 已登记参数：键名来自我方静态表，无需过黑名单。
            # 这一分支是必需的——黑名单含 `token` 子串会误伤 `max_tokens`，
            # 而它是完全合法的登记参数名（源项目把该检查放在自定义键路径上，等价于此处）。
            if is_value_empty(value):
                continue
            errors.extend(_check_one(param, value))
            continue
        # 未登记参数：走安全校验，可能降级为警告透传
        if not is_safe_custom_key(key):
            errors.append(f"参数名 {key!r} 含不允许的字符或敏感词，已拒绝")
            continue
        warnings.append(f"参数 {key} 不在 {spec.label} 的定义表中，可能不会生效")

    return errors, warnings
