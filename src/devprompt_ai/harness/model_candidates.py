"""路由候选解析（G2）：settings 注册表 → 候选链。

候选 = 设置中心里 model_id 与 base_url 均非空的条目，顺序即注册顺序（主备序）。
每次调用现读 settings.json（小文件，读一次 <1ms）并现查 routing_stats，
**不做进程内缓存**——缓存的键必须含配置 hash（MUST-14），而现读天然无 staleness。
"""

from __future__ import annotations

import time
from typing import Any, Final

from devprompt_ai.memory.routing_stats import SQLiteRoutingStats
from devprompt_ai.memory.settings_store import read_model_registry

_STATS_TTL_S: Final[float] = 60.0


def load_candidates() -> list[dict[str, Any]]:
    """有效候选条目（保持注册顺序）；写侧已校验过 model_id/base_url，这里再防脏数据。"""
    registry = read_model_registry()
    models = registry.get("models") if isinstance(registry, dict) else None
    if not isinstance(models, list):
        return []
    return [
        dict(entry)
        for entry in models
        if isinstance(entry, dict)
        and str(entry.get("model_id") or "").strip()
        and str(entry.get("base_url") or "").strip()
    ]


#: 路由统计的进程内缓存：(过期时刻, db_path, stats)。60s 内不重复读库。
_stats_cache: tuple[float, str, dict[tuple[str, str], tuple[int, int, int]]] | None = None


async def load_routing_stats(
    db_path: str,
) -> dict[tuple[str, str], tuple[int, int, int]]:
    """读 bandit 统计；同库 60s 内复用（MUST-14 的缓存键即 db_path + 时间窗）。"""
    global _stats_cache
    now = time.monotonic()
    if _stats_cache is not None and _stats_cache[1] == db_path and now < _stats_cache[0]:
        return _stats_cache[2]
    stats = await SQLiteRoutingStats(db_path).load_all()
    _stats_cache = (now + _STATS_TTL_S, db_path, stats)
    return stats


def invalidate_routing_stats_cache() -> None:
    """测试注入点：清空统计缓存。"""
    global _stats_cache
    _stats_cache = None
