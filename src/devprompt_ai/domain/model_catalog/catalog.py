"""模型目录的合并、回落与标注（纯领域，零 I/O）。

**为什么要合并**：模型窗口有两个来源且都可能缺失——厂商端点 `/models` 的实时返回
（权威、新鲜，但只有部分厂商给窗口），与人工逐条核实的静态表（可靠，但会随发版过期）。
本模块把两者合成**一条唯一的回落链**，并给每个条目标注来源，让「这个窗口是哪来的」
在 UI 与日志里都可见：

    条目选中档位 → catalog 动态窗口 → 静态 MODEL_SPECS（模型级）
    → 静态 PROVIDER_SPECS（厂商级） → None（不判定、不告警）

不变量（对应 F-921 验收）：

- 每个档位都 ≤ 该条目的窗口上限——挡住「选 1M 实际 200K」的假安全感；
- 档位是**告警预算刻度**（`model_spec.window_tiers`：厂商档位 ∪ 128K 起的 2 的幂阶梯），
  因此**允许低于标称窗口**——厂商多半不提供档位，只给标称值用户就调不动告警阈值；
- 窗口未登记时档位恒为空——没有窗口就没有「可选档位」可言；
- 本模块**不做超限判定**，那在 `model_spec.context_window_alert`（MUST-08 单一来源）。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from devprompt_ai.domain.model_catalog.ports import RemoteModelInfo
from devprompt_ai.domain.model_spec import (
    MODEL_SPECS,
    PROVIDER_SPECS,
    max_context_length_of,
    model_meta_of,
    resolve_provider_key,
    window_tiers,
)

#: 条目窗口的来源：`remote` = 端点实时返回；`static` = 静态表兜底（远端为空时）。
CatalogSource = Literal["remote", "static"]


@dataclass(frozen=True, slots=True)
class ModelCatalogItem:
    """下拉里的一个模型选项。"""

    model_id: str
    label: str
    max_context_length: int | None = None
    context_window_tiers: tuple[int, ...] = ()
    #: 该模型的思考强度档位（如 low/high/max）；空元组 = 厂商未提供，不展示该项。
    #: 按模型粒度各自独立——不同厂商/模型的档位不可共用一份清单。
    reasoning_efforts: tuple[str, ...] = ()
    #: 官方标注的默认强度；空 = 取第一档
    default_effort: str = ""
    source: CatalogSource = "remote"
    #: 已配置但不在当前目录中（厂商下架 / 中转站隐藏）。存量配置不失效，仅标注。
    is_stale: bool = False


def _clean_efforts(efforts: Iterable[str]) -> tuple[str, ...]:
    """去重并保持厂商给出的顺序（顺序即厂商的推荐顺序，UI 按序渲染）。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in efforts:
        value = str(raw).strip()
        if value == "" or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


def clean_tiers(tiers: Iterable[int], limit: int | None) -> tuple[int, ...]:
    """去重、升序，并丢弃超过窗口上限的档位。

    远端给了档位但我们窗口未知时一律丢弃：没有上限就无法证明该档位合法，宁可少给。
    """
    if limit is None:
        return ()
    unique = {int(tier) for tier in tiers if isinstance(tier, int) and tier > 0}
    return tuple(sorted(tier for tier in unique if tier <= limit))


def static_catalog(provider: str) -> list[ModelCatalogItem]:
    """静态模型表里该厂商已核实的条目（远端为空时的兜底集合）。"""
    provider_key = resolve_provider_key(provider)
    spec = PROVIDER_SPECS.get(provider_key)
    if spec is None:
        return []
    items: list[ModelCatalogItem] = []
    for meta in MODEL_SPECS.get(provider_key, ()):
        window = meta.max_context_length or spec.max_context_length
        items.append(
            ModelCatalogItem(
                model_id=meta.model_id,
                label=meta.label or meta.model_id,
                max_context_length=window,
                context_window_tiers=clean_tiers(
                    window_tiers(window, meta.context_window_tiers or spec.context_window_tiers),
                    window,
                ),
                reasoning_efforts=meta.reasoning_efforts,
                default_effort=meta.default_effort,
                source="static",
            )
        )
    return items


def merge_catalog(
    remote: Sequence[RemoteModelInfo],
    *,
    provider: str,
    static_items: Sequence[ModelCatalogItem] | None = None,
) -> list[ModelCatalogItem]:
    """合并远端清单与静态表。

    - **远端非空** → 以远端条目为准（动态优先，用户能选到刚发布的新模型），
      静态值只用来补远端没给的窗口与档位；
    - **远端为空** → 回落到静态条目（拉不到时下拉仍可用，但来源标注为 ``static``）。

    条目内的窗口回落：远端值 → 静态模型级值 → 静态厂商级值 → None。
    """
    provider_key = resolve_provider_key(provider)
    spec = PROVIDER_SPECS.get(provider_key)
    provider_window = spec.max_context_length if spec else None
    provider_tiers = spec.context_window_tiers if spec else ()

    if not remote:
        return list(static_items) if static_items is not None else static_catalog(provider)

    lookup = {item.model_id.strip().lower(): item for item in (static_items or ())}
    merged: list[ModelCatalogItem] = []
    for info in remote:
        model_id = info.model_id.strip()
        if not model_id:
            continue  # 畸形条目：直接丢弃，不让它污染下拉
        fallback = lookup.get(model_id.lower())
        window = info.max_context_length or (fallback.max_context_length if fallback else None)
        if window is None:
            window = provider_window
        tiers = info.context_window_tiers or (fallback.context_window_tiers if fallback else ())
        merged.append(
            ModelCatalogItem(
                model_id=model_id,
                label=info.display_name or (fallback.label if fallback else "") or model_id,
                max_context_length=window,
                context_window_tiers=clean_tiers(
                    window_tiers(window, tiers or provider_tiers), window
                ),
                # 强度档位实时优先，静态模型级兜底（官方文档核实过的值）
                reasoning_efforts=_clean_efforts(info.reasoning_efforts)
                or (fallback.reasoning_efforts if fallback else ()),
                default_effort=(fallback.default_effort if fallback else ""),
                source="remote",
            )
        )
    return merged


def mark_stale_models(
    catalog: Sequence[ModelCatalogItem],
    configured_ids: Iterable[str],
    *,
    provider: str = "",
) -> list[ModelCatalogItem]:
    """把已配置但不在目录里的模型置顶并标注（存量配置不失效）。

    用户裁定的语义：厂商下架或中转站隐藏模型时，已配条目仍要能在下拉里选到并选中，
    否则一次刷新就会让用户「配好的模型选不中」。其窗口回落静态表（可能未知 → None）。
    """
    known = {item.model_id.strip().lower() for item in catalog}
    stale: list[ModelCatalogItem] = []
    for raw in configured_ids:
        model_id = raw.strip()
        if not model_id or model_id.lower() in known:
            continue
        stale.append(
            ModelCatalogItem(
                model_id=model_id,
                label=f"{model_id}（不在当前列表）",
                max_context_length=max_context_length_of(provider, model_id),
                context_window_tiers=(),
                source="static",
                is_stale=True,
            )
        )
    return [*stale, *catalog]


def _pick_tier(selected_tier: int | None, tiers: Sequence[int], window: int | None) -> int | None:
    """档位在合法集合内即采用，否则回落标称窗口。

    合法集合恒由 :func:`window_tiers` 算出（厂商档位 ∪ 阶梯），故越界值——包括超过
    标称窗口的「假安全感」——一律回落，不在此处二次判定（MUST-08）。
    """
    if selected_tier is not None and selected_tier in tiers:
        return selected_tier
    return window


def effective_context_window(
    provider: str,
    model_id: str,
    selected_tier: int | None,
    catalog: Sequence[ModelCatalogItem],
) -> int | None:
    """该模型当前生效的上下文窗口（F-921 回落链，动态优先）。

    :param selected_tier: 条目上选中的档位；不在合法档位内 → 用标称值
    :returns: 有效窗口；**全程未知时返回 ``None``**（调用方据此不判定、不告警）
    """
    item = find_item(catalog, model_id)
    if item is not None:
        return _pick_tier(selected_tier, item.context_window_tiers, item.max_context_length)
    # catalog 里没有该模型 → 走静态链（模型级 → 厂商级），档位同样按阶梯补齐
    window = max_context_length_of(provider, model_id)
    spec = PROVIDER_SPECS.get(resolve_provider_key(provider))
    meta = model_meta_of(provider, model_id)
    vendor_tiers = (meta.context_window_tiers if meta else ()) or (
        spec.context_window_tiers if spec else ()
    )
    return _pick_tier(selected_tier, window_tiers(window, vendor_tiers), window)


def find_item(catalog: Sequence[ModelCatalogItem], model_id: str) -> ModelCatalogItem | None:
    """按 model_id 查目录条目（大小写不敏感）；查不到返回 ``None``。"""
    candidate = (model_id or "").strip().lower()
    if not candidate:
        return None
    for item in catalog:
        if item.model_id.strip().lower() == candidate:
            return item
    return None
