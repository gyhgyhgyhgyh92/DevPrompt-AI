"""F-805 成本监控验收：单次优化 token 用量明细（Jev 与 LLM 分别计）+ state 截断。

① 快照携带 cost 明细，jev_tokens / llm_tokens 分源；Jev 未启用时 jev 计 0 且来源如实标注；
② state 组装的硬限（MUST-09）超限即截断而非报错，并记 `state.truncated` 事件（SHOULD-08）。

用例不发起真实网络请求（SHOULD-11）：决策/生成用 fake，Jev 走 transport 之外直接触发
`_fit_state`（纯函数，无需 transport）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest

from devprompt_ai.common.cost import add_jev_tokens, add_llm_tokens, take_tokens
from devprompt_ai.config import AppConfig
from devprompt_ai.decision.fallback import is_jev_enabled
from devprompt_ai.decision.jev import JevDecider
from devprompt_ai.domain.decision.port import (
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
from devprompt_ai.domain.ranking.ports import AdoptionRecord, PreferenceStore
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.interfaces.api import routes
from devprompt_ai.service import _RANK_CACHE, CostBreakdown, FlowSnapshot, ForgeService


@pytest.fixture(autouse=True)
def _reset_cost_accumulators() -> None:
    """成本累计器为进程级 ContextVar，用例间显式清零避免跨用例污染。"""
    take_tokens()


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

    async def list_recent(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        return []

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None


class FakeDecider:
    """三方法全接：每次调用按 as_jev 累加估算（Jev）或实际（LLM 版）用量。"""

    def __init__(self, confs: list[float], tokens_per_call: int, *, as_jev: bool) -> None:
        self.confs = confs
        self.tokens_per_call = tokens_per_call
        self._record = add_jev_tokens if as_jev else add_llm_tokens

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        self._record(self.tokens_per_call)
        return FactProbeOutput(
            judgments=[
                FactJudgment(key=f.key, passed=c >= 0.75, confidence=c)
                for f, c in zip(facts, self.confs, strict=False)
            ],
            overall_confidence=sum(self.confs) / len(self.confs) if self.confs else 0.0,
        )

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        self._record(self.tokens_per_call)
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        self._record(self.tokens_per_call)
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


class FakePreferenceStore:
    """内存偏好存储（PreferenceStore 最小实现，无 I/O）。"""

    def __init__(self) -> None:
        self.vectors: dict[str, dict[str, float]] = {}

    async def load(self, user_id: str) -> dict[str, float]:
        vector = self.vectors.get(user_id)
        return dict(vector) if vector is not None else dict(INITIAL_PREFERENCE)

    async def save(self, user_id: str, vector: dict[str, float]) -> None:
        self.vectors[user_id] = dict(vector)

    async def record_adoption(self, rec: AdoptionRecord) -> None:
        return None

    async def clear_adoptions(self, user_id: str) -> int:
        return 0


def _symbols() -> list[Symbol]:
    return [
        Symbol(name="SubmitButton", path="src/ui/button.tsx", line=12, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/ui/button_group.tsx", line=30, kind="function"),
        Symbol(name="SubmitForm", path="src/ui/form.tsx", line=8, kind="function"),
    ]


def _service(
    *,
    with_jev: bool,
    decision_tokens_per_call: int = 100,
    llm_tokens_per_call: int = 1000,
    existing: set[str] | None = None,
) -> tuple[ForgeService, FakeStore]:
    cfg = AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        typesafe_api_key="test-key" if with_jev else "",
    )
    store = FakeStore()
    prefs: PreferenceStore = FakePreferenceStore()
    svc = ForgeService(
        cfg=cfg,
        # with_jev 时决策层为 Jev（估算入 jev 桶）；否则为 LLM 版（实际入 llm 桶）
        decider=FakeDecider([0.9] * 7, decision_tokens_per_call, as_jev=with_jev),
        sessions=store,
        preferences=prefs,
        runner=FakeRunner(),
        reader=FakeReader(
            existing if existing is not None else {"src/ui/button.tsx", "src/ui/button.test.tsx"}
        ),
        generator=FakeGenerator(llm_tokens_per_call),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    return svc, store


# ---------- ① 成本明细（Jev / LLM 分源） ----------


async def test_cost_detail_separates_jev_and_llm() -> None:
    svc, _ = _service(with_jev=True)
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.cost is not None
    assert snap.cost.jev_tokens > 0  # 决策层 Jev（估算）
    assert snap.cost.llm_tokens == 1000  # 生成器 LLM（实际）
    assert snap.cost.total_tokens == snap.cost.jev_tokens + snap.cost.llm_tokens
    assert snap.cost.jev_source == "estimated"
    assert snap.cost.llm_source == "actual"


async def test_cost_jev_disabled_zero_and_annotated() -> None:
    svc, _ = _service(with_jev=False)
    assert is_jev_enabled(svc._cfg) is False  # noqa: SLF001
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.cost is not None
    assert snap.cost.jev_tokens == 0  # 未启用 Jev → 计 0
    assert snap.cost.jev_source == "not_enabled"  # 如实标注来源
    # 决策层走 LLM 版（3 次调用 ×100）+ 生成器 1000，全部计入 llm 桶
    assert snap.cost.llm_tokens == 1300
    assert snap.cost.llm_source == "actual"


async def test_cost_accumulates_across_requests() -> None:
    """跨请求累计：optimize（ask，仅决策调用）→ followup（done，含生成）逐段入账。"""
    svc, _ = _service(with_jev=True, existing={"src/ui/button.tsx"})
    ask = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert ask.status == "ask"
    assert ask.cost is not None
    assert ask.cost.jev_tokens == 200  # rank_components + probe_facts 各 100
    assert ask.cost.llm_tokens == 0  # 尚未生成

    done = await svc.ask_followup(
        "local",
        ask.session_id,
        {"test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert done.status == "done"
    assert done.cost is not None
    assert done.cost.jev_tokens == 400  # 追加 probe_facts + score_prompts 各 100
    assert done.cost.llm_tokens == 1000  # 生成器入账
    assert done.cost.total_tokens == 1400


# ---------- 契约渲染（routes 薄壳只做镜像，MUST-10） ----------


def test_snapshot_payload_renders_cost_detail() -> None:
    snapshot = FlowSnapshot(
        session_id="s1",
        status="done",
        state="DONE",
        cost=CostBreakdown(
            jev_tokens=10,
            llm_tokens=20,
            total_tokens=30,
            jev_source="estimated",
            llm_source="actual",
        ),
    )
    payload = routes._snapshot_payload(snapshot)
    assert payload.cost is not None
    assert payload.cost.jev_tokens == 10
    assert payload.cost.llm_tokens == 20
    assert payload.cost.total_tokens == 30
    assert payload.cost.jev_source == "estimated"
    assert payload.cost.llm_source == "actual"


def test_snapshot_payload_cost_absent_when_none() -> None:
    snapshot = FlowSnapshot(session_id="s1", status="done", state="DONE")
    assert routes._snapshot_payload(snapshot).cost is None


# ---------- ② state 截断（MUST-09 / SHOULD-08） ----------


def _jev_cfg(*, max_state_tokens: int) -> AppConfig:
    return AppConfig(
        _env_file=None,  # type: ignore[call-arg]
        typesafe_api_key="test-key",
        max_state_tokens=max_state_tokens,
    )


def test_state_over_limit_truncated_emits_event(caplog: pytest.LogCaptureFixture) -> None:
    decider = JevDecider(_jev_cfg(max_state_tokens=10))
    oversized = "上下文" * 100
    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        fitted = decider._fit_state(oversized)  # noqa: SLF001
    assert len(fitted) <= 10  # 截断而非报错
    assert any(
        r.getMessage() == "state.truncated" and getattr(r, "reason", "") == "state-over-limit"
        for r in caplog.records
    )


def test_state_within_limit_not_truncated(caplog: pytest.LogCaptureFixture) -> None:
    decider = JevDecider(_jev_cfg(max_state_tokens=10_000))
    state = "短状态"
    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        fitted = decider._fit_state(state)  # noqa: SLF001
    assert fitted == state
    assert not any(r.getMessage() == "state.truncated" for r in caplog.records)


# ---------- 累计器原语 ----------


def test_take_tokens_accumulates_then_resets() -> None:
    add_llm_tokens(100)
    add_llm_tokens(5)
    add_jev_tokens(40)
    assert take_tokens() == (105, 40)
    assert take_tokens() == (0, 0)


def test_add_zero_is_noop() -> None:
    add_llm_tokens(0)
    add_jev_tokens(0)
    assert take_tokens() == (0, 0)
