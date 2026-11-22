"""agentmemory 适配器测试（2026-11-22）。

用 httpx.MockTransport 拦住真实网络，校验四件事：
请求形状（双桶 agentId / Bearer / body 字段）、单桶失败降级、密钥缺失短路、
响应形状未知时不抛（宽松解析）。所有用例都不依赖真实侧车。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
import pytest

from devprompt_ai.domain.reflection.port import ReflectionNote, ReflectionScope
from devprompt_ai.harness import agentmemory
from devprompt_ai.harness.agentmemory import AgentMemoryReflection

Handler = Callable[[httpx.Request], httpx.Response]
ROOT = "/repo"


def _project_bucket() -> str:
    digest = hashlib.sha1(ROOT.encode("utf-8")).hexdigest()[:12]
    return f"devprompt-proj-{digest}"


def _adapter(secret_path: Path | str) -> AgentMemoryReflection:
    return AgentMemoryReflection(
        base_url="http://am.test",
        secret_path=str(secret_path),
        bucket_prefix="devprompt",
        top_k=4,
        timeout_seconds=1.0,
    )


def _patch(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    """把适配器的 client 换成 MockTransport，并记录每一次请求。"""
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def _client(self: AgentMemoryReflection) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://am.test", transport=httpx.MockTransport(_record))

    monkeypatch.setattr(AgentMemoryReflection, "_client", _client)
    agentmemory.reset_cooldown()
    return seen


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    path = tmp_path / "secret"
    path.write_text("s3cret\n", encoding="utf-8")
    return path


def _body(request: httpx.Request) -> dict[str, object]:
    """请求体解析：agentId 必须走 body（实测 query 会被忽略）。"""
    assert request.content, f"{request.url} 无请求体"
    return cast(dict[str, object], json.loads(request.content.decode("utf-8")))


def _search_response(request: httpx.Request) -> httpx.Response:
    agent_id = str(_body(request).get("agentId", ""))
    if agent_id.endswith("-global"):
        return httpx.Response(200, json={"results": [{"title": "全局经验", "score": 0.4}]})
    return httpx.Response(200, json={"results": [{"title": "项目经验", "score": 0.8}]})


class TestRecall:
    async def test_queries_both_buckets_with_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, _search_response)

        hits = await _adapter(secret_file).recall(
            sentence="改成 primary-500", domain="code", project_root=ROOT
        )

        assert len(seen) == 2
        assert all(item.url.path == "/agentmemory/smart-search" for item in seen)
        agent_ids = sorted(str(_body(item)["agentId"]) for item in seen)
        assert agent_ids == sorted([_project_bucket(), "devprompt-global"])
        assert all(item.headers["authorization"] == "Bearer s3cret" for item in seen)
        assert {hit.text for hit in hits} == {"项目经验", "全局经验"}
        assert {hit.scope for hit in hits} == {ReflectionScope.PROJECT, ReflectionScope.GLOBAL}

    async def test_request_carries_query_limit_and_agent_id(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, _search_response)

        await _adapter(secret_file).recall(
            sentence="改成 primary-500", domain="code", project_root=ROOT
        )

        body = _body(seen[0])
        assert "改成 primary-500" in str(body["query"])
        assert body["limit"] == 2  # top_k=4 → 每桶一半
        assert str(body["agentId"]) in (_project_bucket(), "devprompt-global")
        assert len(seen[0].url.params) == 0  # agentId 不进 query

    async def test_single_bucket_failure_keeps_other(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(_body(request)["agentId"]).endswith("-global"):
                return httpx.Response(500)
            return httpx.Response(200, json={"results": [{"title": "项目经验", "score": 0.8}]})

        _patch(monkeypatch, handler)

        hits = await _adapter(secret_file).recall(sentence="s", domain="code", project_root=ROOT)

        assert [hit.text for hit in hits] == ["项目经验"]

    async def test_missing_secret_sends_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen = _patch(monkeypatch, _search_response)

        hits = await _adapter(tmp_path / "absent").recall(
            sentence="s", domain="code", project_root=ROOT
        )

        assert hits == ()
        assert seen == []

    async def test_failure_trips_cooldown(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, lambda request: httpx.Response(500))
        adapter = _adapter(secret_file)

        assert await adapter.recall(sentence="s", domain="code", project_root=ROOT) == ()
        first_round = len(seen)
        assert first_round == 2

        # 60 秒内不再发请求：只留一次「空结果」，不重复等超时
        assert await adapter.recall(sentence="s", domain="code", project_root=ROOT) == ()
        assert len(seen) == first_round

    async def test_unknown_response_shape_is_tolerated(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        _patch(monkeypatch, lambda request: httpx.Response(200, json={"weird": 1}))

        hits = await _adapter(secret_file).recall(sentence="s", domain="code", project_root=ROOT)

        assert hits == ()

    async def test_items_without_text_field_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        _patch(
            monkeypatch,
            lambda request: httpx.Response(200, json={"items": [{"id": "x"}, {"text": "有效"}]}),
        )

        hits = await _adapter(secret_file).recall(sentence="s", domain="code", project_root=ROOT)

        # 两桶各返回同一条（handler 不区分桶），只保留有正文的那一项
        assert [hit.text for hit in hits] == ["有效", "有效"]

    async def test_blank_sentence_skips_network(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, _search_response)

        assert (
            await _adapter(secret_file).recall(sentence="   ", domain="code", project_root=ROOT)
        ) == ()
        assert seen == []


class TestRecord:
    async def test_project_note_goes_to_project_bucket(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
        note = ReflectionNote(
            scope=ReflectionScope.PROJECT,
            summary="目标=ObservabilityPage；取证=3/4",
            project_root=ROOT,
            domain="code",
            stop_reason="natural-finish",
            target="ObservabilityPage",
            paths=("frontend/src/pages/ObservabilityPage.tsx",),
        )

        assert (await _adapter(secret_file).record(note)) is True

        assert len(seen) == 1
        assert seen[0].url.path == "/agentmemory/remember"
        body = _body(seen[0])
        assert body["agentId"] == _project_bucket()
        assert "ObservabilityPage" in str(body["content"])
        assert "code" in cast(list[str], body["concepts"])

    async def test_global_note_strips_paths_and_target(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
        note = ReflectionNote(
            scope=ReflectionScope.GLOBAL,
            summary="领域=code；终止=natural-finish",
            project_root=ROOT,
            domain="code",
            stop_reason="natural-finish",
            target="ShouldNotLeak",
            paths=("/secret/path.ts",),
        )

        await _adapter(secret_file).record(note)

        body = _body(seen[0])
        assert body["agentId"] == "devprompt-global"
        assert "ShouldNotLeak" not in str(body["content"])
        assert "/secret/path.ts" not in str(body["content"])
        assert body["concepts"] == ["code", "natural-finish"]

    async def test_write_failure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        _patch(monkeypatch, lambda request: httpx.Response(503))
        note = ReflectionNote(scope=ReflectionScope.GLOBAL, summary="领域=code")

        # 不抛、且如实返回 False（调用方据此不报「已记录」）
        assert (await _adapter(secret_file).record(note)) is False

    async def test_blank_summary_skips_network(
        self, monkeypatch: pytest.MonkeyPatch, secret_file: Path
    ) -> None:
        seen = _patch(monkeypatch, lambda request: httpx.Response(200))

        assert (
            await _adapter(secret_file).record(
                ReflectionNote(scope=ReflectionScope.GLOBAL, summary="  ")
            )
        ) is False
        assert seen == []

    async def test_secret_missing_skips_network(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen = _patch(monkeypatch, lambda request: httpx.Response(200))

        await _adapter(tmp_path / "absent").record(
            ReflectionNote(scope=ReflectionScope.GLOBAL, summary="领域=code")
        )

        assert seen == []
