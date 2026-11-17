"""模型注册表（G1–G2）：每个模型的窗口、输出、缓存类型、超时与能力档。

压缩与路由都只依赖这里的元数据，不关心具体供应商；这样新增厂商只需加一条 spec。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from devprompt_ai.domain.context.compact_policy import CacheKind


class ModelTier(str, Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    provider: str = ""
    api_mode: str = "chat_completions"
    context_window: int = 1_048_576
    max_output: int = 64_000
    cache_kind: CacheKind = CacheKind.AUTOMATIC
    timeout_s: float = 60.0
    thinking: str = "adaptive"
    tier: ModelTier = ModelTier.STANDARD


#: 供应商默认缓存能力：精确缓存才算「压一次毁前缀」，其余按无缓存处理。
_PROVIDER_CACHE: Final[dict[str, CacheKind]] = {
    "deepseek": CacheKind.AUTOMATIC,
    "anthropic": CacheKind.EXPLICIT,
    "glm": CacheKind.NONE,
    "mimo": CacheKind.NONE,
}


def infer_cache_kind(provider: str) -> CacheKind:
    return _PROVIDER_CACHE.get((provider or "").strip().lower(), CacheKind.NONE)


class ModelRegistry:
    def __init__(self, specs: list[ModelSpec]) -> None:
        self._specs = {spec.model_id: spec for spec in specs}

    def get(self, model_id: str) -> ModelSpec | None:
        return self._specs.get(model_id)

    def by_tier(self, tier: ModelTier) -> list[ModelSpec]:
        return [spec for spec in self._specs.values() if spec.tier is tier]

    def all(self) -> list[ModelSpec]:
        return list(self._specs.values())


def default_registry(
    *,
    model_id: str,
    provider: str = "",
    api_mode: str = "chat_completions",
    context_window: int = 1_048_576,
    max_output: int = 64_000,
    timeout_s: float = 60.0,
) -> ModelRegistry:
    """从现有单模型配置构造注册表；后续多模型只需追加 spec。"""
    return ModelRegistry(
        [
            ModelSpec(
                model_id=model_id,
                provider=provider,
                api_mode=api_mode,
                context_window=context_window,
                max_output=max_output,
                cache_kind=infer_cache_kind(provider),
                timeout_s=timeout_s,
            )
        ]
    )
