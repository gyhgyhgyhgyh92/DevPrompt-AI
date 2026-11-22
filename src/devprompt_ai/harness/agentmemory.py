"""agentmemory 经验库适配器（2026-11-22，reflection 旁路）。

契约来源：``scripts/probe_agentmemory.py`` 对真实侧车（0.9.33 / iii-engine 0.25.1）
的实测结果，见 ``tests/fixtures/agentmemory/``。两条与 README 不同的关键事实：

1. ``agentId`` 必须放在 **body**，放 query 会被忽略（remember 落进默认空间）；
2. ``smart-search`` 的命中项正文在 ``title`` 字段，**不含** ``content``。

其余仍做宽松解析（列表容器 ``results``/``items``/... 逐级尝试，缺字段跳过该条），
以便侧车小版本调整字段时退化为「本轮无经验」而不是报错。

设计约束：
- 全部异步，每次调用自建 ``httpx.AsyncClient`` 并即时关闭（不持有长连接）；
- 任何失败只 ``emit_warning`` 一条（不带 URL/响应体/原句），绝不抛给调用方；
- 侧车不可用后 60 秒内直接短路，避免每轮白等连接超时；
- 全局桶强制剥离 target/paths（跨项目共享，隐私边界比项目内更严）。
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import httpx

from devprompt_ai.domain.reflection.port import (
    ReflectionHit,
    ReflectionNote,
    ReflectionScope,
)
from devprompt_ai.observability.logging import emit_warning

#: 侧车不可用后的短路窗口（秒）：与 model_candidates 的 60s 缓存同口径。
COOLDOWN_SECONDS: Final = 60.0
#: 建连超时上限（秒）：侧车在本机，1.5s 足够，避免把全部预算花在建连上。
CONNECT_TIMEOUT: Final = 1.5
#: 单条经验写入上限（字符）：项目桶 800、全局桶 300（全局更严，跨项目可见）。
MAX_NOTE_CHARS: Final[dict[ReflectionScope, int]] = {
    ReflectionScope.PROJECT: 800,
    ReflectionScope.GLOBAL: 300,
}
#: 响应里可能出现的列表容器键（实测 0.9.33 用 ``results``；其余为兼容候选）。
_LIST_KEYS: Final = ("results", "items", "memories", "data", "hits")
#: 单条命中的正文键候选：实测 smart-search 只给 ``title``，不含 content。
_TEXT_KEYS: Final = ("title", "content", "text", "memory", "summary", "value")
#: 单条命中的分数键候选。
_SCORE_KEYS: Final = ("score", "relevance", "similarity", "rank_score")

_cooldown_until: float = 0.0


def reset_cooldown() -> None:
    """重置短路窗口（测试用；生产无调用方）。"""
    global _cooldown_until
    _cooldown_until = 0.0


def _in_cooldown() -> bool:
    return time.monotonic() < _cooldown_until


# 健康探测已下沉到 ``common/health_probe.py``（api 层不得 import harness，MUST-06）。


def _trip_cooldown() -> None:
    global _cooldown_until
    _cooldown_until = time.monotonic() + COOLDOWN_SECONDS


def _pick_items(payload: Any) -> Sequence[Mapping[str, Any]]:
    """从响应中取出条目列表：兼容「直接是 list」与「包在 items/results/... 里」。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in _LIST_KEYS:
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, Mapping)]
    return []


def _text_of(item: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _score_of(item: Mapping[str, Any]) -> float:
    for key in _SCORE_KEYS:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


class AgentMemoryReflection:
    """``ReflectionPort`` 的 agentmemory 实现（双桶：项目 / 全局）。"""

    def __init__(
        self,
        *,
        base_url: str,
        secret_path: str,
        bucket_prefix: str,
        top_k: int,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret_path = Path(secret_path).expanduser()
        self._bucket_prefix = bucket_prefix
        self._top_k = top_k
        self._timeout_seconds = timeout_seconds
        self._secret_cache: str | None = None
        self._warned_missing = False

    # ---- 内部工具 ----

    def _secret(self) -> str:
        """惰性读 Bearer 密钥；缺失时只告警一次（后续静默，避免刷日志）。"""
        if self._secret_cache is not None:
            return self._secret_cache
        try:
            self._secret_cache = self._secret_path.read_text(encoding="utf-8").strip()
        except OSError:
            self._secret_cache = ""
        if self._secret_cache == "" and not self._warned_missing:
            self._warned_missing = True
            emit_warning("reflection.skipped", reason="secret_missing")
        return self._secret_cache

    def _bucket_id(self, scope: ReflectionScope, project_root: str) -> str:
        if scope is ReflectionScope.GLOBAL:
            return f"{self._bucket_prefix}-global"
        digest = hashlib.sha1(project_root.encode("utf-8")).hexdigest()[:12]
        return f"{self._bucket_prefix}-proj-{digest}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout_seconds, connect=CONNECT_TIMEOUT),
        )

    @staticmethod
    def _headers(secret: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}

    # ---- 读取 ----

    async def _search(
        self, secret: str, agent_id: str, query: str, limit: int, scope: ReflectionScope
    ) -> list[ReflectionHit]:
        """查一个桶；失败上抛由 ``recall`` 统一降级（单桶失败不影响另一桶）。"""
        async with self._client() as client:
            # agentId 必须走 body：实测 0.9.33 忽略 query 上的 agentId（会落到默认空间）
            resp = await client.post(
                "/agentmemory/smart-search",
                json={"query": query, "limit": limit, "agentId": agent_id},
                headers=self._headers(secret),
            )
            resp.raise_for_status()
            payload = resp.json()
        hits: list[ReflectionHit] = []
        for item in _pick_items(payload):
            text = _text_of(item)
            if text == "":
                continue
            hits.append(ReflectionHit(scope=scope, text=text, score=_score_of(item)))
        return hits

    async def recall(
        self, *, sentence: str, domain: str, project_root: str
    ) -> tuple[ReflectionHit, ...]:
        """并发查两桶并合并；任一步失败返回已拿到的部分（全失败返回空）。"""
        if sentence.strip() == "" or _in_cooldown():
            return ()
        secret = self._secret()
        if secret == "":
            return ()
        query = f"{sentence.strip()} {domain}".strip()
        per_bucket = max(1, self._top_k // 2)
        scopes = (ReflectionScope.PROJECT, ReflectionScope.GLOBAL)
        try:
            results = await asyncio.gather(
                *(
                    self._search(
                        secret, self._bucket_id(scope, project_root), query, per_bucket, scope
                    )
                    for scope in scopes
                ),
                return_exceptions=True,
            )
        except Exception as exc:  # noqa: BLE001 - 旁路：任何异常都降级
            self._degrade("recall", exc)
            return ()

        hits: list[ReflectionHit] = []
        failed = False
        for result in results:
            if isinstance(result, BaseException):
                failed = True
                continue
            hits.extend(result)
        if failed:
            self._degrade("recall", None)
        return tuple(hits)

    # ---- 写入 ----

    async def _remember(self, secret: str, note: ReflectionNote, agent_id: str) -> None:
        limit = MAX_NOTE_CHARS[note.scope]
        content = {note.domain, note.stop_reason}
        if note.scope is ReflectionScope.PROJECT and note.target:
            content.add(note.target)
        concepts = sorted(item for item in content if item)
        async with self._client() as client:
            # 同上：agentId 走 body 才会落进对应桶
            resp = await client.post(
                "/agentmemory/remember",
                json={"content": note.summary[:limit], "concepts": concepts, "agentId": agent_id},
                headers=self._headers(secret),
            )
            resp.raise_for_status()

    async def record(self, note: ReflectionNote) -> bool:
        """写入一条经验；全局桶强制剥离 target/paths（隐私边界）。返回是否已提交。"""
        if _in_cooldown() or note.summary.strip() == "":
            return False
        secret = self._secret()
        if secret == "":
            return False
        safe = (
            note
            if note.scope is ReflectionScope.PROJECT
            else ReflectionNote(
                scope=note.scope,
                summary=note.summary,
                domain=note.domain,
                stop_reason=note.stop_reason,
            )
        )
        try:
            await self._remember(secret, safe, self._bucket_id(safe.scope, note.project_root))
        except Exception as exc:  # noqa: BLE001 - 旁路：写入失败只告警
            self._degrade("record", exc)
            return False
        return True

    def _degrade(self, op: str, exc: BaseException | None) -> None:
        """降级：短路 60 秒并留一条结构化告警（只记操作名与异常类型）。"""
        _trip_cooldown()
        emit_warning(
            "reflection.failed",
            op=op,
            reason=type(exc).__name__ if exc is not None else "bucket_error",
        )
