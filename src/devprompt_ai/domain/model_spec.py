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

from collections.abc import Iterable, Mapping
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
    """该模型的上下文窗口上限；**模型级优先，未登记回落厂商级**；未知返回 ``None``。

    :param provider: provider key（大小写不敏感）
    :param model_id: 模型 id——命中 :data:`MODEL_SPECS` 时取模型级值，否则用厂商级值
    """
    spec = PROVIDER_SPECS.get(resolve_provider_key(provider))
    if spec is None:
        return None
    meta = model_meta_of(provider, model_id)
    if meta is not None and meta.max_context_length is not None:
        return meta.max_context_length
    return spec.max_context_length


#: 上下文窗口告警阈值：``估算 / 有效窗口 > 该值`` 即提示（F-921）。
#:
#: 用比例而非绝对值——档位跨度可达 4 倍，同一条绝对阈值在 300K 档误报、1M 档漏报，
#: 换模型或换档位就得重填一次。留 10% 余量给系统提示词与模型响应。
CONTEXT_ALERT_RATIO: Final[float] = 0.9


def context_window_alert(estimated_tokens: int, limit: int | None) -> bool:
    """估算 token 是否该告警（纯函数；MUST-08：判定不落在接口层与前端）。

    :param limit: 有效窗口 = 条目档位，未选时回落厂商标称；``None``/非正 = 窗口未知，不告警
    """
    if limit is None or limit <= 0:
        return False
    # 整数比较避免浮点误差：estimated / limit > 0.9 等价于 estimated * 10 > limit * 9
    return estimated_tokens * 10 > limit * 9


#: 档位阶梯下限（128K）。低于此值不提供刻度，只给厂商标称窗口。
_TIER_FLOOR: Final[int] = 131_072


def window_tiers(window: int | None, vendor_tiers: Iterable[int] = ()) -> tuple[int, ...]:
    """可选窗口档位 = 厂商档位 ∪ 128K 起的 2 的幂阶梯，限 ≤ ``window``、升序去重。

    阶梯是**超限告警的预算刻度**而非厂商规格——厂商多半不提供档位（DeepSeek 两个模型
    官方只写 CONTEXT LENGTH 1M，无档位概念），只给标称值用户就调不动告警阈值。故取并集
    而非覆盖厂商档位，且恒含标称值本身（供「跟随厂商」回落）。``window`` 未登记时返回空
    元组：没有窗口就无从谈档位。
    """
    if window is None or window <= 0:
        return ()
    tiers = {window, *(t for t in vendor_tiers if 0 < t <= window)}
    step = _TIER_FLOOR
    while step <= window:
        tiers.add(step)
        step *= 2
    return tuple(sorted(tiers))


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
    - `base_url`：官方端点。**查证不到的留空字符串**，由 UI 提示用户自行查询文档填写
      （2026-09-17 逐个 web_search 核实，不得凭印象书写）。
    - `needs_key`：该厂商是否要求非空 api_key。当前全部为 `True`（字段保留，供将来
      出现免鉴权厂商时使用，不预先为其写入条目）。
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
    base_url: str = ""
    needs_key: bool = True
    quirks: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "api_mode": self.api_mode,
            "supported_api_modes": sorted(self.supported_api_modes),
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
        base_url="https://api.x.ai/v1",
    ),
    # ---- 国内主力 ----
    "deepseek": ProviderSpec(
        key="deepseek",
        max_context_length=1_048_576,
        context_window_tiers=(1_048_576,),
        label="DeepSeek",
        aliases=frozenset({"deepseek"}),
        supports_reasoning=True,
        api_mode="chat_completions",
        # anthropic_messages 依据（2026-10-19 核实）api-docs.deepseek.com/guides/anthropic_api：
        # 官方提供 Anthropic Messages 兼容层，base_url=https://api.deepseek.com/anthropic。
        # 官方本体的 base_url 单值装不下 /anthropic 变体，故仍登记 OpenAI 主端点，
        # 变体由用户在设置面板另建一条供应商记录并自填该 base_url。
        supported_api_modes=frozenset({"chat_completions", "anthropic_messages"}),
        base_url="https://api.deepseek.com",
        quirks=(
            "reasoner 模型需开 thinking；V3 系不支持 reasoning_effort。"
            "选原生 Messages 形态需另建一条供应商记录、"
            "base_url 填 https://api.deepseek.com/anthropic（不要手动追加 /v1/messages），"
            "并需已安装 anthropic 依赖；官方会忽略 budget_tokens/top_k/service_tier"
        ),
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
        base_url="https://api-inference.modelscope.cn/v1",
        quirks="免费额度限频率；模型 id 形如 厂商/模型名",
    ),
    # ---- 自定义 / 泛称 ----
    # 自定义：base_url 留空由用户自填，因此端点说什么协议只有用户知道
    # ——形态必须由用户选，限制成两种 OpenAI 形态会让「自定义」名剧其实。
    "custom": ProviderSpec(
        key="custom",
        max_context_length=None,
        label="自定义",
        aliases=frozenset({"custom", "自定义"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset(ALL_API_MODES),
        base_url="",
    ),
    # 同自定义：端点由用户自填，因此允许全部形态
    "openai_compatible": ProviderSpec(
        key="openai_compatible",
        max_context_length=None,
        label="OpenAI 兼容（通用）",
        aliases=frozenset({"openai-compatible", "兼容"}),
        api_mode="chat_completions",
        supported_api_modes=frozenset(ALL_API_MODES),
        base_url="",
    ),
    # 2026-10-17 移除本地推理引擎（ollama / vllm / lmstudio）：它们的模型清单走
    # /api/tags 而非 OpenAI 兼容的 /models，动态目录无从拉取。旧配置里的这些
    # provider 会落到 `openai_compatible` 兜底（resolve_provider_key 不抛错）。
}

#: 未登记厂商的兜底：给出中性参数集 + 保守能力，**不抛错**（裁定 D4：不引内置目录）。
_FALLBACK_PROVIDER_KEY: Final[str] = "openai_compatible"

#: 别名 → 规范 provider key（大小写不敏感）。
_ALIAS_INDEX: Final[dict[str, str]] = {
    alias.lower(): spec.key for spec in PROVIDER_SPECS.values() for alias in spec.aliases
}
_ALIAS_INDEX.update({key: key for key in PROVIDER_SPECS})

# ---------------------------------------------------------------------------
# 模型级元数据（2026-10-17 下沉）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelMeta:
    """单个模型的元数据。

    为什么从 `ProviderSpec` 下沉：同厂商不同模型的窗口与能力可能不同（如 DeepSeek
    同期的 flash 与 pro 定位不同），厂商级单值表达不了，下拉里选错模型就拿到错的告警阈值。

    字段缺省即「未登记」，**回落 provider 级的值**——所以只登记确实核实过的模型，
    其余模型的行为与下沉前完全一致（零回退）。
    """

    model_id: str
    label: str = ""
    #: 该模型的输入窗口上限；``None`` = 未登记，回落 provider 级
    max_context_length: int | None = None
    #: 该模型可单选的档位集合（升序），空 = 只能用标称值
    context_window_tiers: tuple[int, ...] = ()
    #: 该模型官方给出的思考强度档位（按模型粒度，**各模型不可共用一份清单**）；
    #: 空 = 厂商未提供，UI 不展示该段而不是编造选项。
    reasoning_efforts: tuple[str, ...] = ()
    #: 官方标注的默认强度（打开思考模式而未显式选档时用）；空 = 取第一档
    default_effort: str = ""
    #: ``None`` = 沿用 provider 级能力位
    supports_reasoning: bool | None = None

    def to_dict(self, window: int | None, vendor_tiers: tuple[int, ...]) -> dict[str, Any]:
        """``window``/``vendor_tiers`` 传厂商级值：模型级未登记时档位仍要算得出来。"""
        return {
            "model_id": self.model_id,
            "label": self.label or self.model_id,
            "max_context_length": self.max_context_length,
            "context_window_tiers": list(window_tiers(window, vendor_tiers)),
            "reasoning_efforts": list(self.reasoning_efforts),
            "default_effort": self.default_effort,
        }


#: 模型目录：provider key → 该厂商**已核实**的模型元数据。
#:
#: 逐条查官方文档录入（2026-10-17），查不到就不录——**禁填占位默认值**
#: （假窗口比不显示更糟，会让告警拿一个不存在的上限做判定）。
#:
#: DeepSeek 数值来源：
#: - 窗口：DeepSeek API Docs《Models & Pricing》（api-docs.deepseek.com/quick_start/pricing）
#:   ——两模型 CONTEXT LENGTH 均为 1M、MAX OUTPUT 384K，官方**未提供** context length
#:   档位，故 tiers 为单值（UI 上的多档由 `window_tiers` 的告警预算阶梯生成）。
#: - 思考强度：DeepSeek API Docs《Thinking Mode》（api-docs.deepseek.com/guides/thinking_mode）
#:   ——`reasoning_effort` 取值 `none/low/high/max`（`none` 表示关闭思考模式），
#:   且文档注明「思考模式默认打开，effort 默认为 high」。
#: - `/models` 文档（api-docs.deepseek.com/api/list-models）明说该端点会返回
#:   「支持的推理强度(effort)档位」，故实时目录优先、本表兜底。
MODEL_SPECS: Final[dict[str, tuple[ModelMeta, ...]]] = {
    "deepseek": (
        ModelMeta(
            model_id="deepseek-flash",
            label="DeepSeek-V4.1-Flash",
            max_context_length=1_048_576,
            context_window_tiers=(1_048_576,),
            reasoning_efforts=("low", "high", "max"),
            default_effort="high",
            supports_reasoning=True,
        ),
        ModelMeta(
            model_id="deepseek-v4-pro",
            label="DeepSeek-V4-Pro",
            max_context_length=1_048_576,
            context_window_tiers=(1_048_576,),
            reasoning_efforts=("low", "high", "max"),
            default_effort="high",
            supports_reasoning=True,
        ),
    ),
}

#: (provider key, 小写 model_id) → 元数据。model_id 大小写不敏感（厂商文档常混用大小写）。
_MODEL_INDEX: Final[dict[tuple[str, str], ModelMeta]] = {
    (provider_key, meta.model_id.strip().lower()): meta
    for provider_key, metas in MODEL_SPECS.items()
    for meta in metas
}


def model_meta_of(provider: str, model_id: str = "") -> ModelMeta | None:
    """查模型级元数据；未登记（厂商未录、模型未录、或 id 为空）返回 ``None``。

    查不到不是错误——调用方据此回落 provider 级，保持与下沉前一致的行为。
    """
    provider_key = resolve_provider_key(provider)
    candidate = (model_id or "").strip().lower()
    if not candidate:
        return None
    return _MODEL_INDEX.get((provider_key, candidate))


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def resolve_provider_key(provider: str) -> str:
    """把用户填的厂商名解析为规范 key；未登记则回落通用兼容档，**不抛错**。"""
    candidate = (provider or "").strip().lower()
    return _ALIAS_INDEX.get(candidate, _FALLBACK_PROVIDER_KEY)


def resolve_capabilities(provider: str, model_id: str = "") -> ModelCapabilities:
    """解析模型能力。**模型级优先，未登记回落厂商级**；未知厂商走保守默认。"""
    spec = PROVIDER_SPECS[resolve_provider_key(provider)]
    meta = model_meta_of(provider, model_id)
    if meta is None:
        return ModelCapabilities(
            supports_tools=spec.supports_tools,
            supports_reasoning=spec.supports_reasoning,
            max_context_length=spec.max_context_length,
        )
    return ModelCapabilities(
        supports_tools=spec.supports_tools,
        supports_reasoning=(
            spec.supports_reasoning if meta.supports_reasoning is None else meta.supports_reasoning
        ),
        max_context_length=(
            spec.max_context_length if meta.max_context_length is None else meta.max_context_length
        ),
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
    - `context_window_tiers` 是 max_context_length 的可选档位（厂商档位 ∪ 128K 起的
      2 的幂阶梯，见 :func:`window_tiers`）；
    - `models` 是该厂商**已核实**的模型级目录（空 = 未登记，前端回落厂商级值）。

    字段与契约 `ProviderDirectoryEntry` 一一对应（**刻意不复用 `spec.to_dict()`**：
    后者不含内部字段，且用 `key` 而非契约的 `id`）。
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
            "context_window_tiers": list(
                window_tiers(spec.max_context_length, spec.context_window_tiers)
            ),
            "models": [
                meta.to_dict(
                    meta.max_context_length or spec.max_context_length,
                    meta.context_window_tiers or spec.context_window_tiers,
                )
                for meta in MODEL_SPECS.get(key, ())
            ],
            "supports_reasoning": spec.supports_reasoning,
            "quirks": spec.quirks,
        }
        for key, spec in PROVIDER_SPECS.items()
    ]
