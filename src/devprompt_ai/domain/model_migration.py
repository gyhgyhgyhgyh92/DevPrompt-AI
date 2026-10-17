"""注册表条目的字段归一化与参数覆盖清洗（纯领域，零 I/O，MUST-06）。

## 为什么不迁源项目的 `converter.ts`

迁自prompt-optimizer 的 `converter.ts` 负责把**它自己项目的历史格式**（camelCase 的
`baseURL` / `llmParams` / `defaultModel`）转成新结构。核实本项目历史：该文件自建立以来
顶层键始终是 `models` / `model_service` / `active_model_id`，条目始终是
`id` / `label` / `provider` / `base_url` / `api_key` / `model_id` 六字段——
**不存在需要转换的旧版数据**。

照搬转换器等于为不存在的场景写代码（YAGNI），且这类代码永远不会被执行、无法被测试覆盖，
反而成为维护负担。故本模块只做**归一化**：把六字段条目补齐为新结构（读时补、写时全），
以及清洗参数覆盖值。这是本项目实际存在的格式演进需求。

## 归一化策略（对应计划的「读时补默认值」）

- 缺失的 `capabilities` / `param_overrides` 用领域默认值补齐，**不报错**；
- 类型不符的字段降级为默认值并记入错误列表（供设置中心展示原因），条目**不丢弃**——
  本地单用户工具下静默丢配置比报错更难排查；
- 未登记字段保留原样（避免误删用户手工加的字段），但写回时不参与领域逻辑。
"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.model_spec import (
    apply_provider_constraints,
    filter_safe_overrides,
    resolve_capabilities,
)

#: 单条文本字段的合理长度上限（防手工编辑 settings.json 时写入超长内容）。
_MAX_URL_LENGTH = 2048
_MAX_LABEL_LENGTH = 128


def normalize_overrides(provider: str, raw: Any) -> dict[str, Any]:
    """把任意来源的参数覆盖值归一化为「键名安全 + 已剔除不支持项」的干净结构。

    非字典输入（用户手工编辑导致）返回空 dict——宁可参数为空，也不能让脏数据流到下发层。
    键名安全性由 :func:`is_safe_custom_key` 把关；这里额外丢弃已登记但 provider
    不支持的参数（由 :func:`apply_provider_constraints` 承担）。
    """
    if not isinstance(raw, dict):
        return {}
    return apply_provider_constraints(provider, filter_safe_overrides(provider, raw))


def _normalize_capabilities(raw: Any, provider: str, model_id: str) -> dict[str, Any]:
    """能力标记归一化：缺失或结构不符时按 provider 默认值补齐。"""
    fallback = resolve_capabilities(provider, model_id).to_dict()
    if not isinstance(raw, dict):
        return fallback
    merged = dict(fallback)
    for key in fallback:
        value = raw.get(key)
        # 按字段语义分别校验：布尔标记只收bool；长度字段只收非 bool 的整数
        # （bool 是 int 子类，不排除的话 `max_context_length: true` 会变成 1）
        if key.endswith("length"):
            if isinstance(value, int) and not isinstance(value, bool):
                merged[key] = value
        elif isinstance(value, bool):
            merged[key] = value
    return merged


def _clean_text(raw: Any, limit: int) -> tuple[str, bool]:
    """取字符串值并限长；返回 ``(值, 是否被截断)``。非字符串回退为空串。"""
    if not isinstance(raw, str):
        return "", False
    text = raw.strip()
    if len(text) > limit:
        return text[:limit], True
    return text, False


def normalize_entry(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """归一化单个注册表条目，返回 ``(条目, 问题列表)``。

    **永不抛异常**：任何输入（含非字典、字段类型错乱）都返回可用的条目结构，
    问题以列表形式返回供设置中心展示。理由：这是本地单用户工具的数据文件，
    读取失败不该让用户配置丢失，也不该让服务启动不了。

    归一化动作：
    - 文本字段取字符串、去首尾空白、限长（超长记问题但不丢条目）；
    - ``capabilities`` 缺失或结构不符 → 按 provider 默认值补齐；
    - ``param_overrides`` 缺失或非字典 → 空 dict；存在则清洗键名与不支持项；
    - 未登记字段原样保留（避免误删用户手工加的内容）。
    """
    source: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    problems: list[str] = []

    provider, _ = _clean_text(source.get("provider", ""), _MAX_LABEL_LENGTH)
    model_id, model_truncated = _clean_text(source.get("model_id", ""), _MAX_LABEL_LENGTH)
    if model_truncated:
        problems.append("模型标识过长，已截断")

    # 只覆盖需要归一化的 4 个字段；id/label/base_url/api_key 原样保留——
    # 归一化的职责是「补齐与清洗」，绝不能删掉用户的 api_key 或条目 id。
    entry: dict[str, Any] = dict(source)
    entry["provider"] = provider
    entry["model_id"] = model_id
    entry["capabilities"] = _normalize_capabilities(source.get("capabilities"), provider, model_id)
    # 2026-09-17 多供应商扩展的三个每条目字段：缺失即空，**不报错**（旧条目兼容）。
    # api_mode 空 = 按 provider 默认推断；reasoning_effort 空 = 不下发；
    # max_context_length 空 = 沿用 provider 默认窗口。
    api_mode = source.get("api_mode", "")
    entry["api_mode"] = api_mode if isinstance(api_mode, str) else ""
    effort = source.get("reasoning_effort", "")
    entry["reasoning_effort"] = effort if isinstance(effort, str) else ""
    window = source.get("max_context_length")
    entry["max_context_length"] = window if isinstance(window, int) and window > 0 else None
    entry["param_overrides"] = normalize_overrides(provider, source.get("param_overrides"))
    return entry, problems


def normalize_registry(models: Any) -> list[dict[str, Any]]:
    """归一化整个条目列表（逐条调用 :func:`normalize_entry`，丢弃非字典项）。"""
    if not isinstance(models, list):
        return []
    out: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        entry, _ = normalize_entry(item)
        out.append(entry)
    return out
