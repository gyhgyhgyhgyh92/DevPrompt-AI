"""F-805 成本监控验收：单次优化 token 用量明细（LLM 实际用量累计）。

① 快照携带 cost 明细，llm_tokens / total_tokens 同源（来源如实标注 llm_source）；
② 累计器原语：跨请求累计、取用后清零。

用例不发起真实网络请求（SHOULD-11）：决策/生成用 fake。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest

from devprompt_ai.common.cost import add_llm_tokens, take_llm_tokens
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import (
    AskQuestion,
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.generate.ports import (
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    SessionSummary,
    Symbol,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.interfaces.api import routes
from devprompt_ai.service import _RANK_CACHE, CostBreakdown, FlowSnapshot, ForgeService


@pytest.fixture(autouse=True)
def _reset_cost_accumulators() -> None:
    """成本累计器为进程级 ContextVar，用例间显式清零避免跨用例污染。"""
    take_llm_tokens()


@pytest.fixture(autouse=True)
def _isolated_rank_cache() -> None:
    _RANK_CACHE.clear()


@dataclass(slots=True)
class FakeStore:
    items: dict[str, FlowSession] = field(default_factory=dict)

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        return []

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        return 0  # 本用例不覆盖项目级删除（详见 test_session_store.py）


class FakeDecider:
    """三方法全接：每次调用累加决策层 token 用量（LLM 实际入 llm 桶）。"""

    def __init__(self, confs: list[float], tokens_per_call: int) -> None:
        self.confs = confs
        self.tokens_per_call = tokens_per_call

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        add_llm_tokens(self.tokens_per_call)
        judgments = [
            FactJudgment(key=f.key, passed=c >= 0.75, confidence=c)
            for f, c in zip(facts, self.confs, strict=False)
        ]
        # 反问时机由决策层给出（2026-10-20）：只对真实缺口提问，等价旧行为
        gaps = [
            j.key for j, f in zip(judgments, facts, strict=False) if not (f.passed and j.passed)
        ]
        return FactProbeOutput(
            judgments=judgments,
            overall_confidence=sum(self.confs) / len(self.confs) if self.confs else 0.0,
            questions=[AskQuestion(key=k, question=f"请确认 {k}") for k in gaps],
        )

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        add_llm_tokens(self.tokens_per_call)
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        add_llm_tokens(self.tokens_per_call)
        return ScorePromptsOutput(
            scores=[
                VariantScore(variant=cast(Literal["A", "B", "C"], key), score=3, confidence=0.9)
                for key, _ in variants
            ]
        )


class FakeGenerator:
    """生成器：累加 `llm_tokens_per_call`（模拟 chat_structured 的 SDK usage）。"""

    def __init__(self, llm_tokens_per_call: int) -> None:
        self.llm_tokens_per_call = llm_tokens_per_call

    async def generate_single(self, ctx: GenerationContext) -> VariantDraft:
        add_llm_tokens(self.llm_tokens_per_call)
        return VariantDraft(title="t", body="b", changes=["x"], level=ctx.level)

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level]
    ) -> MultiVariantDraft:
        add_llm_tokens(self.llm_tokens_per_call)
        return MultiVariantDraft(
            variants=[VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels]
        )

    async def answer(self, ctx: GenerationContext) -> str:
        add_llm_tokens(self.llm_tokens_per_call)
        return "回答"


class FakeRunner:
    """按 rg 参数内容路由：symbol/token/testid/states 查询各返回命中行。"""

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        routes_map = [
            ("SubmitButton", "src/ui/button.tsx:12:SubmitButton"),
            ("--color-x", "src/styles/tokens.css:1:  --color-x: #3b82f6"),
            ("data-testid", "src/ui/button.tsx:14:  data-testid='s'"),
            (":hover", "src/ui/button.tsx:20:  .btn:hover"),
        ]
        for needle, out in routes_map:
            if any(needle in a for a in args[2:]):
                return out
        return ""


class FakeReader:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing

    async def read(self, path: str) -> str:
        return (
            "export function SubmitButton() { return <button data-testid='s' "
            "class='btn btn:hover'/> } /* --color-x */"
        )

    async def exists(self, path: str) -> bool:
        return path in self.existing


def _symbols() -> list[Symbol]:
    return [
        Symbol(name="SubmitButton", path="src/ui/button.tsx", line=12, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/ui/button_group.tsx", line=30, kind="function"),
        Symbol(name="SubmitForm", path="src/ui/form.tsx", line=8, kind="function"),
    ]


def _service(
    *,
    decision_tokens_per_call: int = 100,
    llm_tokens_per_call: int = 1000,
    existing: set[str] | None = None,
) -> tuple[ForgeService, FakeStore]:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    store = FakeStore()
    svc = ForgeService(
        cfg=cfg,
        # 决策层为单一 LLM 实现（2026-10-15）：其调用与实际用量一并入 llm 桶
        decider=FakeDecider([0.9] * 7, decision_tokens_per_call),
        sessions=store,
        runner=FakeRunner(),
        reader=FakeReader(
            existing if existing is not None else {"src/ui/button.tsx", "src/ui/button.test.tsx"}
        ),
        generator=FakeGenerator(llm_tokens_per_call),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    return svc, store


# ---------- ① 成本明细（LLM 实际用量） ----------


async def test_cost_detail_llm_only() -> None:
    svc, _ = _service()
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.cost is not None
    # 决策层（rank_components + probe_facts + score_prompts，3 次 ×100）+ 生成器 1000
    assert snap.cost.llm_tokens == 1300
    assert snap.cost.total_tokens == 1300
    assert snap.cost.llm_source == "actual"


async def test_cost_accumulates_across_requests() -> None:
    """跨请求累计：optimize（ask，仅决策调用）→ followup（done，含生成）逐段入账。"""
    svc, _ = _service(existing={"src/ui/button.tsx"})
    ask = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert ask.status == "ask"
    assert ask.cost is not None
    assert ask.cost.llm_tokens == 200  # rank_components + probe_facts 各 100
    assert ask.cost.total_tokens == 200

    done = await svc.ask_followup(
        "local",
        ask.session_id,
        {"请确认 test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert done.status == "done"
    assert done.cost is not None
    # 追加 probe_facts + score_prompts 各 100 + 生成器 1000
    assert done.cost.llm_tokens == 1400
    assert done.cost.total_tokens == 1400


# ---------- 契约渲染（routes 薄壳只做镜像，MUST-10） ----------


def test_snapshot_payload_renders_cost_detail() -> None:
    snapshot = FlowSnapshot(
        session_id="s1",
        status="done",
        state="DONE",
        cost=CostBreakdown(llm_tokens=20, total_tokens=20, llm_source="actual"),
    )
    payload = routes._snapshot_payload(snapshot)
    assert payload.cost is not None
    assert payload.cost.llm_tokens == 20
    assert payload.cost.total_tokens == 20
    assert payload.cost.llm_source == "actual"


def test_snapshot_payload_cost_absent_when_none() -> None:
    snapshot = FlowSnapshot(session_id="s1", status="done", state="DONE")
    assert routes._snapshot_payload(snapshot).cost is None


# ---------- 累计器原语 ----------


def test_take_llm_tokens_accumulates_then_resets() -> None:
    add_llm_tokens(100)
    add_llm_tokens(5)
    assert take_llm_tokens() == 105
    assert take_llm_tokens() == 0


def test_add_zero_is_noop() -> None:
    add_llm_tokens(0)
    assert take_llm_tokens() == 0
