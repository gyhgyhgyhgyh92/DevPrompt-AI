"""多模型平台测试：注册表、任务推断、bandit 路由、客户端池与主备切换。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.domain.context.compact_policy import CacheKind
from devprompt_ai.domain.model.registry import (
    ModelTier,
    default_registry,
    infer_cache_kind,
)
from devprompt_ai.domain.model.task_inferrer import (
    TaskKind,
    complexity_score,
    infer_task,
    tier_for_complexity,
    tier_for_task,
)
from devprompt_ai.harness.fallback import FallbackClient
from devprompt_ai.harness.model_pool import ModelPool


def test_cache_kind_inference_by_provider() -> None:
    assert infer_cache_kind("deepseek") is CacheKind.AUTOMATIC
    assert infer_cache_kind("Anthropic") is CacheKind.EXPLICIT
    assert infer_cache_kind("glm") is CacheKind.NONE
    assert infer_cache_kind("unknown") is CacheKind.NONE


def test_default_registry_builds_single_spec() -> None:
    registry = default_registry(model_id="deepseek-chat", provider="deepseek", timeout_s=45)

    spec = registry.get("deepseek-chat")
    assert spec is not None
    assert spec.cache_kind is CacheKind.AUTOMATIC
    assert spec.timeout_s == 45
    assert registry.by_tier(ModelTier.STANDARD) == [spec]
    assert registry.get("missing") is None


def test_task_inference_and_tiers() -> None:
    assert infer_task("把导出按钮加上") is TaskKind.GENERATE
    assert infer_task("排查一下为什么很慢") is TaskKind.INVESTIGATE
    assert infer_task("审查这段改动的风险") is TaskKind.REVIEW

    assert tier_for_task(TaskKind.GENERATE) is ModelTier.STRONG
    assert tier_for_task(TaskKind.PROBE) is ModelTier.CHEAP
    assert tier_for_complexity(0.8) is ModelTier.STRONG
    assert tier_for_complexity(0.1) is ModelTier.CHEAP


def test_complexity_grows_with_paths_and_length() -> None:
    assert complexity_score("") == 0.0
    assert complexity_score("改一下 src/a.py 里的导出，并补测试") > complexity_score("改一下")


def test_model_pool_is_lru() -> None:
    created: list[str] = []

    def factory(key: Any) -> str:
        created.append(str(key))
        return f"client-{key}"

    pool: ModelPool[str] = ModelPool(factory, capacity=2)
    assert pool.get("a") == "client-a"
    assert pool.get("b") == "client-b"
    assert pool.get("a") == "client-a", "复用不重建"
    pool.get("c")
    assert pool.keys() == ["a", "c"], "最久未用的 b 被淘汰"
    assert created == ["a", "b", "c"]


async def test_fallback_switches_once_and_sticks() -> None:
    calls: list[str] = []

    async def operation(client: str) -> str:
        calls.append(client)
        if client == "primary":
            raise RuntimeError("primary down")
        return "ok"

    client: FallbackClient[str] = FallbackClient("primary", "backup")
    assert await client.call(operation) == "ok"
    assert client.using_backup is True
    assert calls == ["primary", "backup"]

    assert await client.call(operation) == "ok"
    assert calls == ["primary", "backup", "backup"], "切备后不再回主"


async def test_fallback_without_backup_raises() -> None:
    async def operation(client: str) -> str:
        raise RuntimeError(client)

    client: FallbackClient[str] = FallbackClient("primary")
    with pytest.raises(RuntimeError):
        await client.call(operation)
