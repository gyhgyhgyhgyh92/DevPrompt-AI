"""P2 缓存/压缩接线回归：缓存分档、否决门、消息折叠、前缀缓存。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.domain.context.compact_economics import Billing, reclaim_floor
from devprompt_ai.domain.context.compact_policy import CacheKind
from devprompt_ai.domain.context.compactor import confirm_reclaim
from devprompt_ai.domain.model.registry import infer_cache_kind


def test_cache_kind_inference() -> None:
    assert infer_cache_kind("DeepSeek") is CacheKind.AUTOMATIC
    assert infer_cache_kind("anthropic") is CacheKind.EXPLICIT
    assert infer_cache_kind("未知厂商") is CacheKind.NONE


def test_confirm_reclaim_rejects_tiny_gain() -> None:
    floor = reclaim_floor(
        billing=Billing.SUBSCRIPTION, cache_kind=CacheKind.AUTOMATIC, window=300_000
    )
    verdict = confirm_reclaim(before_tokens=10_000, after_tokens=9_999, floor=floor, force=False)
    assert verdict.worthwhile is False
    forced = confirm_reclaim(before_tokens=10_000, after_tokens=9_999, floor=floor, force=True)
    assert forced.worthwhile is True


def test_query_rewrite_detects_target_switch() -> None:
    from devprompt_ai.domain.retrieval.query_rewrite import rewrite_query, target_changed

    # 新符号名 → 目标切换，必须重检索
    switched = rewrite_query("把 LoginButton 改成蓝色", "SubmitButton")
    assert target_changed(switched, "SubmitButton") is True
    # 纯指代 → 沿用旧目标，不重检索
    inherited = rewrite_query("这个按钮改成蓝色", "SubmitButton")
    assert target_changed(inherited, "SubmitButton") is False


def test_llm_rewrite_takes_precedence_and_falls_back() -> None:
    """LLM 改写可用时覆盖规则结果；抛错时静默回退规则结果。"""
    import asyncio

    from devprompt_ai.config import AppConfig
    from devprompt_ai.domain.models import FlowSession
    from devprompt_ai.domain.retrieval.query_rewrite import RewrittenQuery
    from devprompt_ai.harness.process import SymbolTableProvider
    from devprompt_ai.service import ForgeService
    from devprompt_ai.state import FlowState
    from test_service import FakeDecider, FakeGenerator, FakeReader, FakeRunner, FakeStore, _symbols

    class RewriteDecider(FakeDecider):
        def __init__(self, fail: bool = False) -> None:
            super().__init__([0.9] * 7)
            self._fail = fail
            self.calls = 0

        async def rewrite_query(self, sentence: str, previous_target: str = "") -> RewrittenQuery:
            self.calls += 1
            if self._fail:
                raise RuntimeError("boom")
            return RewrittenQuery(
                target="NewTarget", intent="modify", entities=(), negation=(), confidence=0.95
            )

    def _svc(decider: Any) -> ForgeService:
        return ForgeService(
            cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
            decider=decider,
            sessions=FakeStore(),
            runner=FakeRunner(),
            reader=FakeReader({"src/ui/button.tsx"}),
            generator=FakeGenerator(),
            symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
            symbols_override=_symbols(),
        )

    async def _go() -> None:
        ok = RewriteDecider()
        svc = _svc(ok)
        session = FlowSession(
            session_id="s1",
            user_id="local",
            state=FlowState.AGENTIC.value,
            data={"sentence": "改成另一个页面的表格", "project_root": ".", "turn_index": 0},
        )
        await svc._sessions.create(session)  # noqa: SLF001
        await svc._act_retrieve(session, "改成另一个页面的表格", ".", request_id="r1")  # noqa: SLF001
        assert ok.calls == 1
        assert session.data["query_rewrite"]["target"] == "NewTarget"

        bad = RewriteDecider(fail=True)
        svc2 = _svc(bad)
        session2 = FlowSession(
            session_id="s2",
            user_id="local",
            state=FlowState.AGENTIC.value,
            data={"sentence": "把按钮改成蓝色", "project_root": ".", "turn_index": 0},
        )
        await svc2._sessions.create(session2)  # noqa: SLF001
        await svc2._act_retrieve(session2, "把按钮改成蓝色", ".", request_id="r2")  # noqa: SLF001
        assert session2.data["query_rewrite"]["target"] != "NewTarget"

    asyncio.run(_go())


def test_memory_search_without_target() -> None:
    from devprompt_ai.memory.project_note_store import ProjectNote, score_note

    note = ProjectNote(
        project_root="p",
        kind="decision",
        key="x@y",
        value="选定向：A",
        evidence="",
        confidence=0.7,
        hit_count=0,
        last_hit_at="",
        superseded_by="",
        source="test",
    )
    assert score_note(note, target_key="", age_days=0) > 0


def test_search_tool_respects_turn_token_budget() -> None:
    """工具回路回喂前按累计 token 自查：超预算只截尾，不抛错中断生成。"""
    import asyncio

    from devprompt_ai.harness.llm import _search_code_tool

    class FakeRunner:
        async def run(self, args: list[str], **_: Any) -> str:
            return "\n".join(f"src/f{i}.py:{i}:x = 1" for i in range(200))

    tool = _search_code_tool(".", FakeRunner(), budget_tokens=10)  # type: ignore[arg-type]

    async def _go() -> str:
        return await tool.on_invoke_tool(None, '{"query":"x"}')  # type: ignore[arg-type]

    result = asyncio.run(_go())
    assert "超出本轮 token 预算" in str(result)


def test_anthropic_system_has_cache_control() -> None:
    from agents import ModelSettings

    from devprompt_ai.harness.adapters.anthropic_native import AnthropicNativeModel

    model = AnthropicNativeModel("claude-test", client=object(), api_key="k")  # type: ignore[arg-type]
    ms = ModelSettings(max_tokens=4096)
    req = model._build_request(  # noqa: SLF001
        system="stable instructions", messages=[], tools=[], model_settings=ms
    )
    block = req["system"][0]
    assert block["type"] == "text"
    assert block["cache_control"] == {"type": "ephemeral"}
