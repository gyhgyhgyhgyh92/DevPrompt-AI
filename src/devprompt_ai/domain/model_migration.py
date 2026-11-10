"""注册表条目的字段归一化与参数覆盖清洗（纯领域，零 I/O，MUST-06）。

## 为什么不迁源项目的 `converter.ts`

迁自prompt-optimizer 的 `converter.ts` 负责把**它自己项目的历史格式**（camelCase 的
`baseURL` / `llmParams` / `defaultModel`）转成新结构。核实本项目历史：该文件自建立以来
顶层键始终是 `models` / `model_service` / `active_model_id`，条目始终是
`id` / `label` / `provider` / `base_url` / `api_key` / `model_id` 六字段——
**不存在需要转换的旧版数据**。

照搬转换器等于为不存在的场景写代码（YAGNI），且这类代码永远不会被执行、无法被测试覆盖，
反而成为维护负担。故本模块只做**归一化**：把条目补齐为新结构（读时补、写时全），
以及清洗参数覆盖值。这是本项目实际存在的格式演进需求。

## 归一化策略（对应计划的「读时补默认值」）

- 缺失的 `capabilities` 用领域默认值补齐，**不报错**；
- 类型不符的字段降级为默认值并记入错误列表（供设置中心展示原因），条目**不丢弃**——
  本地单用户工具下静默丢配置比报错更难排查；
- 未登记字段保留原样（避免误删用户手工加的字段），但写回时不参与领域逻辑；
- 已下线的 `label`（显示名称，2026-10-18 移除）显式剔除，否则会永久残留在设置文件里。

## 供应商段（2026-10-18 供应商中心化重构）

`settings.json` 新增 `providers` 段：`provider` / `base_url` / `api_key` **只存一份**，
`models[]` 条目瘦身为 `provider_id` + `model_id` + 按模型参数。本模块提供三个纯函数
把两种形态互相转换，让 `settings_store` 边界之外的所有消费方继续看**扁平条目**：

- :func:`attach_providers` —— 读侧：旧格式条目（自带 `provider`/`base_url`/`api_key`、
  无 `provider_id`）按 `(provider, base_url)` 归并进供应商记录，定下 `provider_id`；
- :func:`join_providers` —— 读侧：把记录的端点与密钥展平回条目；
- :func:`split_registry` —— 写侧：反向拆分，条目只留 `provider_id`。

**旧格式迁移的密钥口径**：同一 `(provider, base_url)` 下若多条目带不同密钥，保留第一个
非空值——「一个端点一份密钥」是该重构的既定语义（用户裁定），不同端点仍各自成记录。
"""

from __future__ import annotations

import uuid
from typing import Any

from devprompt_ai.domain.model_spec import (
    model_meta_by_id,
    nearest_context_tier,
    resolve_capabilities,
)

#: 单条文本字段的合理长度上限（防手工编辑 settings.json 时写入超长内容）。
_MAX_URL_LENGTH = 2048
_MAX_TEXT_LENGTH = 128


def _normalize_capabilities(raw: Any, provider: str, model_id: str) -> dict[str, Any]:
    """能力标记归一化：缺失或结构不符时按 provider 默认值补齐。

    2026-11-10：模型 id 有跨厂商登记时**以静态表重算为准**，不沿用落盘值——
    中转站把第三方模型挂在自家厂商名下时，落盘值是按厂商级窗口算出的
    （kimi-k2.6 曾被记成 1M，真实为 256K），与模型事实不符。三个字段都是只读、
    由系统计算，重算不丢用户数据。
    """
    fallback = resolve_capabilities(provider, model_id).to_dict()
    if model_meta_by_id(model_id) is not None:
        return fallback
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
        - 未登记字段原样保留（避免误删用户手工加的内容）。
    """
    source: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    source.pop("label", None)  # 显示名称已下线：先剔除，否则永久残留在设置文件里
    problems: list[str] = []

    provider, _ = _clean_text(source.get("provider", ""), _MAX_TEXT_LENGTH)
    model_id, model_truncated = _clean_text(source.get("model_id", ""), _MAX_TEXT_LENGTH)
    if model_truncated:
        problems.append("模型标识过长，已截断")

    # 只覆盖需要归一化的 4 个字段；id/base_url/api_key 原样保留——
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
    if isinstance(window, int) and window > 0:
        nominal = entry["capabilities"].get("max_context_length")
        entry["max_context_length"] = nearest_context_tier(
            window, nominal if isinstance(nominal, int) else None
        )
    else:
        entry["max_context_length"] = None
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


# ---------------------------------------------------------------------------
# 供应商段（2026-10-18 供应商中心化重构）
# ---------------------------------------------------------------------------


def normalize_provider(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """归一化单个供应商配置记录，返回 ``(记录, 问题列表)``。

    记录字段：``id``（缺省生成 ``p-`` + uuid8）、``provider``（厂商 key）、
    ``base_url``、``api_key``。**api_key 原样保留**——归一化的职责是补齐与清洗，
    绝不能删掉用户的密钥（MUST-19：设置文件是密钥唯一落盘处）。
    """
    source: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    problems: list[str] = []
    provider, _ = _clean_text(source.get("provider", ""), _MAX_TEXT_LENGTH)
    base_url, url_truncated = _clean_text(source.get("base_url", ""), _MAX_URL_LENGTH)
    if url_truncated:
        problems.append("服务地址过长，已截断")
    api_key = source.get("api_key", "")
    record = {
        "id": str(source.get("id") or "").strip() or f"p-{uuid.uuid4().hex[:8]}",
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key if isinstance(api_key, str) else "",
    }
    return record, problems


def normalize_providers(raw: Any) -> list[dict[str, Any]]:
    """归一化供应商记录列表（丢弃非字典项，按 id 去重）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        record, _ = normalize_provider(item)
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        out.append(record)
    return out


def _endpoint_key(provider: str, base_url: str) -> tuple[str, str]:
    """端点归并键：厂商名大小写不敏感，base_url 去首尾空白。"""
    return (provider.strip().lower(), base_url.strip())


def attach_providers(
    models: list[dict[str, Any]], providers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """读侧：给每个条目定下 ``provider_id``，并补上 ``provider``（供能力兜底判定）。

    旧格式条目（自带 ``provider``/``base_url``/``api_key``、无 ``provider_id``）按
    ``(provider, base_url)`` 归并进既有供应商记录；没有则新建。同一归并组里取第一个
    非空密钥——「一个端点一份密钥」是重构既定语义，不同端点仍各自成记录。
    幂等：已有可解析 ``provider_id`` 的条目原样不动。
    """
    records = [dict(p) for p in providers]
    by_id = {p["id"]: p for p in records}
    by_endpoint: dict[tuple[str, str], dict[str, Any]] = {}
    for known in records:
        by_endpoint.setdefault(_endpoint_key(known["provider"], known["base_url"]), known)

    out: list[dict[str, Any]] = []
    for entry in models:
        item = dict(entry)
        provider_id = str(item.get("provider_id") or "").strip()
        record: dict[str, Any] | None = by_id.get(provider_id) if provider_id else None
        if record is None:
            # 旧格式条目或悬空引用：按条目自带的端点信息归并
            key = _endpoint_key(str(item.get("provider") or ""), str(item.get("base_url") or ""))
            record = by_endpoint.get(key)
            if record is None:
                record = {
                    "id": f"p-{uuid.uuid4().hex[:8]}",
                    "provider": str(item.get("provider") or ""),
                    "base_url": str(item.get("base_url") or ""),
                    "api_key": "",
                }
                records.append(record)
                by_id[record["id"]] = record
                by_endpoint[key] = record
            if not record["api_key"]:
                inherited = str(item.get("api_key") or "")
                if inherited:
                    record["api_key"] = inherited
            provider_id = record["id"]
        item["provider_id"] = provider_id
        item["provider"] = record["provider"]
        out.append(item)
    return out, records


def join_providers(
    models: list[dict[str, Any]], providers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """读侧：把供应商记录的端点与密钥展平回条目（内部消费方一律看扁平结构）。"""
    by_id = {p["id"]: p for p in providers}
    out: list[dict[str, Any]] = []
    for entry in models:
        item = dict(entry)
        record = by_id.get(str(item.get("provider_id") or ""))
        item["provider"] = record["provider"] if record else str(item.get("provider") or "")
        item["base_url"] = record["base_url"] if record else str(item.get("base_url") or "")
        item["api_key"] = record["api_key"] if record else str(item.get("api_key") or "")
        out.append(item)
    return out


def split_registry(
    models: list[dict[str, Any]],
    providers: list[dict[str, Any]] | None,
    existing: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """写侧：扁平条目 → ``(落库条目[只留 provider_id + 按模型字段], 落库供应商记录)``。

    - ``providers`` 非 None → **权威列表**（调用方已做完增删）；未出现的记录一并删除，
      其条目随 ``models`` 整表替换消失（用户裁定的级联删除语义）。刚配好、还没勾选任何
      模型的供应商记录也在列表里，故**保留**。
    - ``providers`` 为 None → 只按条目端点派生（旧调用方兼容），id 尽量沿用 ``existing``，
      且只保留被条目引用的记录。
    """
    authoritative = providers is not None
    # 归一化补 id：调用方可能直接传未归一化的记录，落盘结构必须始终完整
    records = normalize_providers(providers if authoritative else existing)
    by_id = {str(p["id"]): p for p in records}
    by_endpoint: dict[tuple[str, str], dict[str, Any]] = {}
    for existing_record in records:
        key = _endpoint_key(existing_record["provider"], existing_record["base_url"])
        by_endpoint.setdefault(key, existing_record)

    entries: list[dict[str, Any]] = []
    for item in models:
        entry = dict(item)
        provider_id = str(entry.pop("provider_id", "") or "").strip()
        provider = str(entry.pop("provider", "") or "")
        base_url = str(entry.pop("base_url", "") or "")
        api_key = str(entry.pop("api_key", "") or "")
        record = by_id.get(provider_id) if provider_id else None
        if record is None:
            record = by_endpoint.get(_endpoint_key(provider, base_url))
        if record is None and authoritative and provider_id:
            # 权威模式下条目指向一个已不在列表里的供应商：该供应商被级联删除，条目随之消失
            continue
        if record is None:
            record = {
                "id": provider_id or f"p-{uuid.uuid4().hex[:8]}",
                "provider": provider,
                "base_url": base_url,
                "api_key": api_key,
            }
            records.append(record)
            by_id[record["id"]] = record
            by_endpoint[_endpoint_key(provider, base_url)] = record
        if api_key and not record["api_key"]:
            record["api_key"] = api_key
        entry["provider_id"] = record["id"]
        entries.append(entry)

    if not authoritative:
        referenced = {str(e.get("provider_id")) for e in entries}
        records = [r for r in records if r["id"] in referenced]
    return entries, records
