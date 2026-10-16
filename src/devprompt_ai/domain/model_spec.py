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

    @property
    def is_native(self) -> bool:
        """是否会被 `ModelSettings` 原生下发（本轮只有原生参数真正生效）。"""
        return self.name in NATIVE_PARAMETERS

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


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """一个厂商的参数与约束定义（裁定 D1：静态表，非适配器）。

    `drop_params` / `force_params` 是 provider 专属知识的唯一载体——源项目把这些写在
    `if (adapterId === 'anthropic')` 分支里，本项目改为数据，从而保持清洗逻辑零分支。
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
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
            description="越高越抑制重复用词",
            min_value=-2.0,
            max_value=2.0,
            step=0.1,
        ),
        ParameterDefinition(
            name="presence_penalty",
            type="number",
            label="存在惩罚",
            description="越高越鼓励引入新话题",
            min_value=-2.0,
            max_value=2.0,
            step=0.1,
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
PROVIDER_SPECS: Final[dict[str, ProviderSpec]] = {
    "openai_compatible": ProviderSpec(
        key="openai_compatible",
        label="OpenAI 兼容（通用）",
        aliases=frozenset({"openai-compatible", "custom", "兼容"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
    ),
    "openai": ProviderSpec(
        key="openai",
        label="OpenAI",
        aliases=frozenset({"openai"}),
        parameters=(*_sampling(2.0), _REASONING_PARAM),
        supports_reasoning=True,
        max_context_length=200000,
    ),
    "deepseek": ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        aliases=frozenset({"deepseek"}),
        parameters=(*_sampling(2.0), _REASONING_PARAM),
        supports_reasoning=True,
        max_context_length=64000,
    ),
    "anthropic": ProviderSpec(
        key="anthropic",
        label="Anthropic",
        aliases=frozenset({"anthropic", "claude"}),
        # Anthropic 原生 API 不接受这些采样参数；本项目走兼容端点时同样剔除更安全。
        # 注意仍保留 max_tokens 定义——剔除发生在下发前，UI 侧不该把它显示成「不支持」。
        parameters=_sampling(2.0),
        drop_params=frozenset({"temperature", "top_p"}),
        force_params={"reasoning_effort": "high"},
        supports_reasoning=True,
        max_context_length=200000,
    ),
    "gemini": ProviderSpec(
        key="gemini",
        label="Google Gemini",
        aliases=frozenset({"gemini", "google"}),
        parameters=_sampling(2.0),
        drop_params=frozenset({"temperature", "top_p", "frequency_penalty", "presence_penalty"}),
        supports_reasoning=True,
        max_context_length=1000000,
    ),
    "grok": ProviderSpec(
        key="grok",
        label="xAI Grok",
        aliases=frozenset({"grok", "xai"}),
        parameters=(*_sampling(2.0), _REASONING_PARAM),
        supports_reasoning=True,
        max_context_length=131072,
    ),
    "zhipu": ProviderSpec(
        key="zhipu",
        label="智谱 GLM",
        aliases=frozenset({"zhipu", "glm", "智谱"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
    ),
    "siliconflow": ProviderSpec(
        key="siliconflow",
        label="硅基流动",
        aliases=frozenset({"siliconflow", "硅基"}),
        parameters=_sampling(2.0),
        max_context_length=128000,
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
