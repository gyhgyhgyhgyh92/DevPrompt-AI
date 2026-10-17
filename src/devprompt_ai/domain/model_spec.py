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
    drop_params: frozenset[str] = frozenset()
    force_params: Mapping[str, Any] = field(default_factory=dict)
    supports_tools: bool = True
    supports_reasoning: bool = False
    #: 厂商标称输入窗口；``None`` = 未登记（查证不到，**勿填占位默认值**——
    #: 假值会让 UI 拿一个不存在的上限做告警判定，比不显示更糟）
    max_context_length: int | None = None
    #: 用户可单选的档位集合（绝对 token，升序）。空元组 = 只能用标称默认值。
    #: 只能取厂商真实支持的规格，且不得大于 ``max_context_length``。
    context_window_tiers: tuple[int, ...] = ()
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
            "context_window_tiers": list(self.context_window_tiers),
        }


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


PROVIDER_SPECS: Final[dict[str, ProviderSpec]] = {
    # ---- 国外 ----
    "openai": ProviderSpec(
        key="openai",
        max_context_length=272000,
        context_window_tiers=(
            128000,
            272000,
        ),
        label="OpenAI",
        aliases=frozenset({"openai"}),
        supports_reasoning=True,
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
        max_context_length=200000,
        context_window_tiers=(
            100000,
            200000,
        ),
        drop_params=frozenset({"temperature", "top_p"}),
        force_params={"reasoning_effort": "high"},
        supports_reasoning=True,
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
        max_context_length=1000000,
        context_window_tiers=(
            200000,
            1000000,
        ),
        drop_params=frozenset({"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        supports_reasoning=True,
        api_mode="gemini_generate_content",
        supported_api_modes=frozenset({"gemini_generate_content", "chat_completions"}),
        adapter_kind="gemini_native",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        quirks="OpenAI 兼容层有并发与配额限制；长上下文按梯度计费",
    ),
    "grok": ProviderSpec(
        key="grok",
        max_context_length=256000,
        context_window_tiers=(
            131072,
            256000,
        ),
        label="xAI Grok",
        aliases=frozenset({"grok", "xai"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.x.ai/v1",
    ),
    # ---- 国内主力 ----
    "deepseek": ProviderSpec(
        key="deepseek",
        max_context_length=128000,
        context_window_tiers=(
            64000,
            128000,
        ),
        label="DeepSeek",
        aliases=frozenset({"deepseek"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.deepseek.com",
        quirks="reasoner 模型需开 thinking；V3 系不支持 reasoning_effort",
    ),
    "dashscope": ProviderSpec(
        key="dashscope",
        max_context_length=262144,
        context_window_tiers=(
            131072,
            262144,
        ),
        label="阿里通义（百炼）",
        aliases=frozenset({"dashscope", "qwen", "tongyi", "阿里"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        quirks="需用 compatible-mode 路径；Coding Plan 套餐有专属 base_url",
    ),
    "zhipu": ProviderSpec(
        key="zhipu",
        max_context_length=200000,
        context_window_tiers=(
            128000,
            200000,
        ),
        label="智谱 GLM",
        aliases=frozenset({"zhipu", "glm", "智谱"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        quirks="base_url 末尾斜杠不可省略",
    ),
    "moonshot": ProviderSpec(
        key="moonshot",
        max_context_length=256000,
        context_window_tiers=(
            128000,
            256000,
        ),
        label="月之暗面 Kimi",
        aliases=frozenset({"moonshot", "kimi"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.moonshot.cn/v1",
    ),
    "volcengine": ProviderSpec(
        key="volcengine",
        max_context_length=262144,
        context_window_tiers=(
            131072,
            262144,
        ),
        label="火山方舟（豆包）",
        aliases=frozenset({"volcengine", "doubao", "ark", "豆包"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        quirks="模型 id 需带推理接入点 ID（ep-xxx），非裸模型名",
    ),
    "qianfan": ProviderSpec(
        key="qianfan",
        max_context_length=131072,
        context_window_tiers=(
            65536,
            131072,
        ),
        label="百度千帆（文心）",
        aliases=frozenset({"qianfan", "ernie", "文心", "百度"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://qianfan.baidubce.com/v2",
        quirks="v2 与旧版地址不兼容；部分模型需 IAM 签名而非 Bearer",
    ),
    "hunyuan": ProviderSpec(
        key="hunyuan",
        max_context_length=192000,
        context_window_tiers=(
            128000,
            192000,
        ),
        label="腾讯混元",
        aliases=frozenset({"hunyuan", "混元", "腾讯"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
    ),
    "spark": ProviderSpec(
        key="spark",
        max_context_length=262144,
        context_window_tiers=(
            131072,
            262144,
        ),
        label="讯飞星火",
        aliases=frozenset({"spark", "xfyun", "讯飞"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://spark-api-open.xf-yun.com/v2",
        quirks="不同模型版本 base_url 路径不同（/v2、/x2）",
    ),
    "minimax": ProviderSpec(
        key="minimax",
        max_context_length=1000000,
        context_window_tiers=(131072, 1000000),
        label="MiniMax",
        aliases=frozenset({"minimax"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.minimaxi.com/v1",
        quirks="中国大陆（minimaxi.com）与海外（minimax.io）Key 与地址不可混用",
    ),
    "stepfun": ProviderSpec(
        key="stepfun",
        max_context_length=262144,
        context_window_tiers=(32768, 262144),
        label="阶跃星辰",
        aliases=frozenset({"stepfun", "阶跃"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.stepfun.com/v1",
    ),
    # ---- 国内长尾 ----
    "baichuan": ProviderSpec(
        key="baichuan",
        max_context_length=196608,
        context_window_tiers=(
            98304,
            196608,
        ),
        label="百川智能",
        aliases=frozenset({"baichuan", "百川"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.baichuan-ai.com",
    ),
    "yi": ProviderSpec(
        key="yi",
        max_context_length=None,
        label="零一万物",
        aliases=frozenset({"yi", "01.ai", "零一"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.lingyiwanwu.com/v1",
    ),
    "sensetime": ProviderSpec(
        key="sensetime",
        max_context_length=None,
        label="商汤（商量）",
        aliases=frozenset({"sensetime", "商汤", "sensecore"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        # 有兼容模式但 base_url 需登录控制台获取（2026-09-17），留空
        base_url="https://token.sensenova.cn/v1",
    ),
    "xiaomi-mimo": ProviderSpec(
        key="xiaomi-mimo",
        max_context_length=None,
        label="小米 MiMo",
        aliases=frozenset({"xiaomi-mimo", "mimo", "小米"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        # 仅找到临时测试域名，非官方稳定端点（2026-09-17），留空
        base_url="https://api.xiaomimimo.com/v1",
    ),
    # ---- 聚合平台 ----
    "siliconflow": ProviderSpec(
        key="siliconflow",
        max_context_length=1000000,
        context_window_tiers=(
            131072,
            1000000,
        ),
        label="硅基流动",
        aliases=frozenset({"siliconflow", "硅基"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api.siliconflow.cn/v1",
        quirks="一个 Key 调用多家模型，模型 id 形如 厂商/模型名",
    ),
    "modelscope": ProviderSpec(
        key="modelscope",
        max_context_length=None,
        label="魔搭 ModelScope",
        aliases=frozenset({"modelscope", "魔搭"}),
        supports_reasoning=False,
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="https://api-inference.modelscope.cn/v1",
        quirks="免费额度限频率；模型 id 形如 厂商/模型名",
    ),
    # ---- 自定义 / 泛称 ----
    "custom": ProviderSpec(
        key="custom",
        max_context_length=None,
        label="自定义",
        aliases=frozenset({"custom", "自定义"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions", "responses"}),
        adapter_kind="openai_compat",
        base_url="",
    ),
    "openai_compatible": ProviderSpec(
        key="openai_compatible",
        max_context_length=None,
        label="OpenAI 兼容（通用）",
        aliases=frozenset({"openai-compatible", "兼容"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions", "responses"}),
        adapter_kind="openai_compat",
        base_url="",
    ),
    # ---- 本地推理引擎（不校验 key）----
    "ollama": ProviderSpec(
        key="ollama",
        max_context_length=None,
        label="Ollama（本地）",
        aliases=frozenset({"ollama"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="http://localhost:11434/v1",
        needs_key=False,
        quirks="api_key 填任意非空占位值；工具调用支持取决于具体模型",
    ),
    "vllm": ProviderSpec(
        key="vllm",
        max_context_length=None,
        label="vLLM（本地）",
        aliases=frozenset({"vllm"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset({"chat_completions"}),
        adapter_kind="openai_compat",
        base_url="http://localhost:8000/v1",
        needs_key=False,
        quirks="需 --enable-auto-tool-choice 才支持函数调用",
    ),
    "lmstudio": ProviderSpec(
        key="lmstudio",
        max_context_length=None,
        label="LM Studio（本地）",
        aliases=frozenset({"lmstudio", "lm-studio"}),
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

    前端据此渲染 provider 下拉、动态表单与**上下文窗口档位下拉**：
    - `base_url` 为空 = **官方端点未登记**（查证不到时如实留空，由 UI 提示自填）；
    - `max_context_length` 为 `None` = **窗口未登记**（同上，勿填占位默认值）；
    - `supported_api_modes` 限制 api_mode 下拉的可选值；
    - `context_window_tiers` 是 max_context_length 的可选档位（空 = 只能用默认）。

    字段与契约 `ProviderDirectoryEntry` 一一对应（**刻意不复用 `spec.to_dict()`**：
    后者含 `adapter_kind` 等内部字段，且用 `key` 而非契约的 `id`）。
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
            "context_window_tiers": list(spec.context_window_tiers),
            "supports_reasoning": spec.supports_reasoning,
            "quirks": spec.quirks,
        }
        for key, spec in PROVIDER_SPECS.items()
    ]
