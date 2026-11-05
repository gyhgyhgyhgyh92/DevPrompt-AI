"""Agentic 循环（service.run_agent_loop）编排测试。

覆盖三条终止路径：模型主动交付、需要用户答复（转 ASKING）、收敛熔断。
装配 planner 时走循环；未装配时 ``optimize`` 自动回落线性流水线（既有 800+ 用例覆盖）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import pytest
from pydantic import ValidationError

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import TERMINAL_ACTIONS, AgentAction, AgentStep
from devprompt_ai.domain.decision.followup import UnknownItem
from devprompt_ai.domain.decision.port import (
    AskOption,
    AskQuestion,
    FactJudgment,
    FactProbeOutput,
    NextActionOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.generate.ports import Claim, Level, MultiVariantDraft, VariantDraft
from devprompt_ai.domain.hooks.types import Hook, HookContext, HookPhase, HookResult
from devprompt_ai.domain.models import (
    FactResult,
    FlowSession,
    SessionSummary,
    Symbol,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.service import ForgeService
from devprompt_ai.state import FlowState


@dataclass
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
        return 0


class FakeRunner:
    """按 rg 参数内容路由，7 项取证全部命中。"""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str]] = [
            ("SubmitButton", "src/ui/button.tsx:12:export function SubmitButton()"),
            ("--color-x", "src/styles/tokens.css:1:  --color-x: #3b82f6"),
            ("data-testid", "src/ui/button.tsx:14:  data-testid='s'"),
            (":hover", "src/ui/button.tsx:20:  .btn:hover"),
        ]

    async def run(self, args: list[str], **kw: Any) -> str:
        for needle, out in self.routes:
            if any(needle in a for a in args[2:]):
                return out
        return ""


#: ctags --output-format=json 的行走势（供 symbols_override=None 的用例）
_CTAGS_JSON = "\n".join(
    [
        '{"_type":"tag","name":"SubmitButton","path":"src/ui/button.tsx","line":12,"kind":"function"}',
        '{"_type":"tag","name":"SubmitButtonGroup","path":"src/ui/button_group.tsx","line":30,"kind":"function"}',
        '{"_type":"tag","name":"SubmitForm","path":"src/ui/form.tsx","line":8,"kind":"function"}',
    ]
)


class CtagsRunner(FakeRunner):
    """ctags 返回固定符号表，rg 走父类路由。"""

    async def run(self, args: list[str], **kw: Any) -> str:
        if args and args[0] == "ctags":
            return _CTAGS_JSON
        return await super().run(args, **kw)


#: verify_facts 用 root 拼绝对路径后查存在性，故此处也必须是绝对路径
_EXISTING_FILES = {
    "C:/proj/src/ui/button.tsx",
    "C:/proj/src/ui/button.test.tsx",
}


class FakeReader:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing

    async def read(self, path: str) -> str:
        return "export function SubmitButton() { return <button/> }"

    async def exists(self, path: str) -> bool:
        return path in self.existing


class FakeGenerator:
    async def generate_single(self, ctx: Any) -> VariantDraft:
        return VariantDraft(title="t", body="b", changes=["x"], level=ctx.level)

    async def generate_variants(self, ctx: Any, levels: Sequence[Level]) -> MultiVariantDraft:
        return MultiVariantDraft(
            variants=[VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels]
        )

    async def answer(self, ctx: Any) -> str:
        return "默认回答"


@dataclass
class ScriptedDecider:
    """按脚本吐动作的决策层替身，同时实现 DecisionPort 三方法。"""

    actions: list[NextActionOutput]
    probe_output: FactProbeOutput | None = None
    calls: int = 0
    rank_calls: int = 0
    score_calls: int = 0
    #: 每次决策收到的外环纠偏提示，供「correct 是否传到下一轮」断言
    corrections: list[str] = field(default_factory=list)

    async def next_action(
        self,
        *,
        sentence: str,
        facts: Sequence[FactResult],
        steps: Sequence[AgentStep],
        variant_count: int,
        clarifications: Mapping[str, str],
        correction: str = "",
    ) -> NextActionOutput:
        out = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        self.corrections.append(correction)
        return out

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        if self.probe_output is not None:
            return self.probe_output
        return FactProbeOutput(
            judgments=[FactJudgment(key=f.key, passed=f.passed, confidence=0.9) for f in facts],
            overall_confidence=0.9,
        )

    async def rank_components(self, sentence: str, candidates: list[Any]) -> RankComponentsOutput:
        self.rank_calls += 1
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        self.score_calls += 1
        return ScorePromptsOutput(
            scores=[VariantScore(variant=key, score=3, confidence=0.9) for key, _ in variants]  # type: ignore[arg-type]
        )


def _symbols() -> list[Symbol]:
    return [
        Symbol(name="SubmitButton", path="src/ui/button.tsx", line=12, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/ui/button_group.tsx", line=30, kind="function"),
        Symbol(name="SubmitForm", path="src/ui/form.tsx", line=8, kind="function"),
    ]


def _service(
    decider: ScriptedDecider,
    *,
    with_override: bool = True,
    generator: Any = None,
) -> tuple[ForgeService, FakeStore]:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    store = FakeStore()
    svc = ForgeService(
        cfg=cfg,
        decider=decider,
        sessions=store,
        runner=FakeRunner(),
        reader=FakeReader(_EXISTING_FILES),
        generator=generator or FakeGenerator(),
        symbols_provider=SymbolTableProvider(CtagsRunner(), ttl_seconds=0.0),
        symbols_override=_symbols() if with_override else None,
    )
    return svc, store


def _action(name: AgentAction, *, confidence: float | None = 0.9) -> NextActionOutput:
    return NextActionOutput(
        action=name.value,
        reason=f"选 {name.value}",
        confidence=confidence,
        confidence_source="measured" if confidence is not None else "no_data",
    )


async def test_loop_delivers_and_records_steps() -> None:
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, store = _service(decider)

    snapshot = await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")

    assert snapshot.state == FlowState.DONE.value
    session = next(iter(store.items.values()))
    steps = session.data["agent_steps"]
    assert [s["action"] for s in steps] == ["retrieve", "probe", "generate", "deliver"]


async def test_loop_stops_at_asking_when_questions_pending() -> None:
    probe = FactProbeOutput(
        judgments=[],
        overall_confidence=0.0,
        questions=[
            AskQuestion(
                key="scope",
                question="改动范围是仅按钮还是整组组件?",
                header="范围",
                options=[AskOption(label="仅按钮"), AskOption(label="整组")],
            )
        ],
        task_kind="design",
    )
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.ASK),
        ],
        probe_output=probe,
    )
    svc, store = _service(decider)

    snapshot = await svc.optimize("local", "C:/proj", "加个导出", request_id="r2")

    assert snapshot.status == "ask"
    assert snapshot.state == FlowState.ASKING.value
    session = next(iter(store.items.values()))
    assert session.data["unknowns"], "未决问题应写入 session.data"


async def test_loop_aborts_when_actions_repeat() -> None:
    """连续重复同一动作：先 L2 警告，达到熔断阈值后终止为 ABORTED。"""
    decider = ScriptedDecider(actions=[_action(AgentAction.GENERATE)] * 8)
    svc, store = _service(decider)

    snapshot = await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r3")

    assert snapshot.state == FlowState.ABORTED.value
    assert snapshot.status == "aborted"
    session = next(iter(store.items.values()))
    assert len(session.data["agent_steps"]) < 8, "熔断应早于脚本耗尽"


async def test_second_turn_inherits_and_reuses_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """第二轮空原句：沿用上一轮目标；代码未变时复用取证，不重跑 ripgrep。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, store = _service(decider, with_override=False)

    first = await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")
    assert first.state == FlowState.DONE.value
    session_id = first.session_id

    decider.actions = [
        _action(AgentAction.RETRIEVE),
        _action(AgentAction.GENERATE),
        _action(AgentAction.DELIVER),
    ]
    decider.calls = 0

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        second = await svc.optimize("local", "C:/proj", "", request_id="r2", session_id=session_id)

    assert second.state == FlowState.DONE.value
    session = store.items[session_id]
    assert session.data["sentence"] == "把 SubmitButton 改成蓝色"
    assert any(record.getMessage() == "evidence.reused" for record in caplog.records)


class HaltHook(Hook):
    """post_tool 直接要求终止。"""

    name = "halt_test"
    phase: HookPhase = "post_tool"

    def run(self, ctx: HookContext) -> HookResult:
        return HookResult(verdict="halt", reason="测试终止")


class FirstCorrectHook(Hook):
    """第一次 post_tool 返回 correct，之后回到 allow。"""

    name = "correct_test"
    phase: HookPhase = "post_tool"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, ctx: HookContext) -> HookResult:
        self.calls += 1
        if self.calls == 1:
            return HookResult(verdict="correct", reason="先补取证再生成")
        return HookResult()


async def test_post_tool_halt_aborts_turn() -> None:
    """halt 由 service 消费：本轮直接 ABORTED，且不再有下一次决策。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, _ = _service(decider, with_override=False)
    svc._hooks.register(HaltHook())

    snapshot = await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")

    assert snapshot.state == FlowState.ABORTED.value
    assert decider.calls == 1, "halt 后不应再有下一次决策"


async def test_post_tool_correct_reaches_next_decision() -> None:
    """correct 的 reason 进入下一次 next_action。"""
    decider = ScriptedDecider(actions=[_action(AgentAction.RETRIEVE), _action(AgentAction.DELIVER)])
    svc, _ = _service(decider, with_override=False)
    svc._hooks.register(FirstCorrectHook())

    await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")

    assert decider.corrections[0] == "", "第一次决策前还没有纠偏"
    assert decider.corrections[1] == "先补取证再生成"


async def test_turn_anchor_merges_across_turns() -> None:
    """目标锚点跨轮追加：objective 不被第二轮重写，范围与约束累加。"""
    decider = ScriptedDecider(actions=[_action(AgentAction.DELIVER)])
    svc, store = _service(decider, with_override=False)

    first = await svc.optimize(
        "local", "C:/proj", "把 SubmitButton 改成蓝色，不要动布局", request_id="r1"
    )
    session_id = first.session_id
    anchor = store.items[session_id].data["turn_anchor"]
    assert anchor["objective"] == "把 SubmitButton 改成蓝色，不要动布局"
    assert anchor["created_at_turn"] == 0

    decider.actions = [_action(AgentAction.DELIVER)]
    decider.calls = 0
    second = await svc.optimize(
        "local", "", "src/ui/button.tsx 也要保持兼容", request_id="r2", session_id=session_id
    )

    assert second.state == FlowState.DONE.value
    anchor = store.items[session_id].data["turn_anchor"]
    assert anchor["objective"] == "把 SubmitButton 改成蓝色，不要动布局"
    assert "src/ui/button.tsx" in anchor["scope_paths"]
    assert anchor["created_at_turn"] == 0
    # 无 TurnStore 时 _begin_turn 不推进 turn_index，故只断言单调不减
    assert anchor["updated_at_turn"] >= anchor["created_at_turn"]


async def test_second_turn_reprobes_when_code_changed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """代码指纹变化 → 不复用取证，记 stale_reprobe。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, store = _service(decider, with_override=False)

    first = await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")
    session_id = first.session_id

    session = store.items[session_id]
    memory_payload = session.data["turn_memory"]
    memory_payload["facts_mtime_digest"] = "digest-from-an-old-checkout"
    await store.save(session)

    decider.actions = [
        _action(AgentAction.RETRIEVE),
        _action(AgentAction.GENERATE),
        _action(AgentAction.DELIVER),
    ]
    decider.calls = 0

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        await svc.optimize("local", "C:/proj", "", request_id="r2", session_id=session_id)

    assert any(record.getMessage() == "evidence.stale_reprobe" for record in caplog.records)


class ClaimGenerator(FakeGenerator):
    """三套方案，claims 覆盖率可控（用于验证 C 档降档）。"""

    def __init__(self, *, covered: int, total: int) -> None:
        self.covered = covered
        self.total = total

    async def generate_variants(self, ctx: Any, levels: Sequence[Level]) -> MultiVariantDraft:
        claims = [
            Claim(kind="file", target="src/ui/button.tsx" if i < self.covered else f"nope_{i}.tsx")
            for i in range(self.total)
        ]
        return MultiVariantDraft(
            variants=[
                VariantDraft(title="t", body="b", changes=[], level=lv, claims=claims)
                for lv in levels
            ]
        )


async def test_c_level_downgrades_when_claims_uncovered() -> None:
    """C 档断言覆盖率不足 → 降到 B 并留痕，不重新生成。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, store = _service(decider, generator=ClaimGenerator(covered=0, total=2))

    await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r1")

    session = next(iter(store.items.values()))
    report = session.data["claim_report"]
    assert report["total"] > 0
    assert report["coverage"] < 0.8
    assert session.data["level"] == "B"
    assert report["summary"].startswith("已核对断言")


async def test_b_level_keeps_level_even_with_uncovered_claims() -> None:
    """只有 C 档受约束：B 档记录报告但不降档（本就非激进输出）。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.PROBE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ],
        probe_output=FactProbeOutput(
            judgments=[],
            overall_confidence=0.5,  # 低于 fact_probe_threshold → facts_complete=False → B 档
        ),
    )
    svc, store = _service(decider, generator=ClaimGenerator(covered=0, total=1))

    await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r2")

    session = next(iter(store.items.values()))
    assert session.data["level"] == "B"
    assert session.data["claim_report"]["total"] > 0


# ── confidence_source 拆分与追问采纳（2026-11-04）────────────────────


def _no_data_probe(
    *, task_kind: str = "execution", questions: list[AskQuestion] | None = None
) -> FactProbeOutput:
    return FactProbeOutput(
        judgments=[],
        overall_confidence=None,
        confidence_source="no_data",
        questions=questions or [],
        task_kind=cast(Literal["design", "execution"], task_kind),
    )


def _optimize_actions() -> list[NextActionOutput]:
    return [
        _action(AgentAction.RETRIEVE),
        _action(AgentAction.PROBE),
        _action(AgentAction.GENERATE),
        _action(AgentAction.DELIVER),
    ]


def test_measured_requires_value() -> None:
    """显式声明 measured 却不给值：契约破坏，构造即失败。"""
    with pytest.raises(ValidationError):
        FactProbeOutput(
            judgments=[],
            overall_confidence=None,
            confidence_source="measured",
        )


_SEVEN_FACT_KEYS = (
    "target_file_exists",
    "symbol_in_file",
    "token_defined",
    "has_data_testid",
    "has_state_styles",
    "file_type_matches",
    "test_file_exists",
)


def _probe_session(store: FakeStore, *, all_pass: bool) -> FlowSession:
    """直接构造一个已定位+已取证的会话，绕开检索链，只测研判判定。"""
    session = FlowSession(
        session_id="s-probe",
        user_id="local",
        state=FlowState.PROBING.value,
        data={
            "sentence": "把 SubmitButton 改成蓝色",
            "target": {"name": "SubmitButton", "path": "src/ui/button.tsx", "line": 12},
            "facts": [
                {"key": key, "passed": all_pass, "evidence": f"{key} evidence"}
                for key in _SEVEN_FACT_KEYS
            ],
            "last_request_id": "r",
        },
    )
    store.items[session.session_id] = session
    return session


async def test_no_data_with_complete_evidence_reaches_complete() -> None:
    """模型未给判断（no_data）+ 七项全过 + 无未决 → 视为信息完备（此前被假 0.0 卡住）。"""
    svc, store = _service(ScriptedDecider(actions=[], probe_output=_no_data_probe()))
    session = _probe_session(store, all_pass=True)

    has_unknowns = await svc._act_probe(session, request_id="r1")

    assert has_unknowns is False
    assert session.data["facts_complete"] is True
    assert session.data["confidence_source"] == "no_data"
    assert session.data["probe_confidence"] is None


async def test_no_data_with_pending_questions_is_not_complete() -> None:
    """确有未决项时仍算不完备——no_data 不等于「一律放行」。"""
    questions = [
        AskQuestion(
            key="scope",
            question="改动范围是仅按钮还是整组组件?",
            header="范围",
            options=[AskOption(label="仅按钮")],
        )
    ]
    svc, store = _service(
        ScriptedDecider(
            actions=[],
            probe_output=_no_data_probe(task_kind="design", questions=questions),
        )
    )
    session = _probe_session(store, all_pass=True)

    has_unknowns = await svc._act_probe(session, request_id="r2")

    assert has_unknowns is True
    assert session.data["facts_complete"] is False


async def test_measured_low_confidence_is_not_complete() -> None:
    svc, store = _service(
        ScriptedDecider(
            actions=[],
            probe_output=FactProbeOutput(
                judgments=[], overall_confidence=0.5, confidence_source="measured"
            ),
        )
    )
    session = _probe_session(store, all_pass=True)

    await svc._act_probe(session, request_id="r3")

    assert session.data["facts_complete"] is False


def test_track_ask_adoption_emits_only_on_repeat(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """首问不计重复；追问轮再次问出同一 key 才记 expect_unmet。"""
    svc, _ = _service(ScriptedDecider(actions=[]))
    session = FlowSession(
        session_id="s-adopt",
        user_id="local",
        state=FlowState.AGENTIC.value,
        data={"rounds": 1, "last_request_id": "r"},
    )
    item = UnknownItem(key="scope", reason="r", best_guess="", ask="范围?")

    svc._track_ask_adoption(session, [item])  # 首次登记
    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        svc._track_ask_adoption(session, [item])  # 重复

    assert any(record.getMessage() == "followup.expect_unmet" for record in caplog.records)
    assert len(session.data["asked_keys"]) == 1


def test_candidates_hash_reflects_candidate_set() -> None:
    """MUST-14 第四段键：候选集变了，旧排序必须失效。"""
    from devprompt_ai.domain.models import Candidate
    from devprompt_ai.service import _candidates_hash

    first = [
        Candidate(
            name="SubmitButton", path="src/ui/button.tsx", line=12, score=5.0, source="symbol"
        )
    ]
    second = [
        Candidate(name="SubmitForm", path="src/ui/form.tsx", line=8, score=4.0, source="symbol")
    ]

    assert _candidates_hash(first) == _candidates_hash(list(first))
    assert _candidates_hash(first) != _candidates_hash(second)
    assert _candidates_hash([]) == _candidates_hash([])


def _design_probe() -> FactProbeOutput:
    return FactProbeOutput(
        judgments=[],
        overall_confidence=None,
        confidence_source="no_data",
        questions=[AskQuestion(key="scope", question="改动范围?")],
        task_kind="design",
    )


async def test_snapshot_exposes_evidence_stale() -> None:
    """过期标记必须透出到快照，否则前端看不到就等于没标。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    session = _probe_session(store, all_pass=True)
    session.data["evidence_stale"] = True

    snap = svc._snapshot(session, "done")

    assert snap.evidence_stale is True


async def test_deliver_flags_stale_evidence() -> None:
    """跳过 RETRIEVING 直接交付时，代码变更必须被标注（真实冒烟发现）。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    session = _probe_session(store, all_pass=True)
    session.data["project_root"] = "C:/proj"
    session.data["facts_mtime_digest"] = "digest-from-an-old-checkout"

    await svc._check_evidence_freshness(session, request_id="r", stage="deliver")

    assert session.data.get("evidence_stale") is True


async def test_generate_without_probe_still_runs_judgment() -> None:
    """agentic 跳过 PROBE 时 GENERATE 前补跑研判——否则档位落到隐式默认 A。"""
    decider = ScriptedDecider(
        actions=[
            _action(AgentAction.RETRIEVE),
            _action(AgentAction.GENERATE),
            _action(AgentAction.DELIVER),
        ]
    )
    svc, store = _service(decider)

    await svc.optimize("local", "C:/proj", "把 SubmitButton 改成蓝色", request_id="r")

    session = next(iter(store.items.values()))
    assert "facts_complete" in session.data
    assert session.data.get("level") in {"A", "B", "C"}


def test_best_guess_skips_not_found_placeholder() -> None:
    """「未找到」是 _ev() 的字面占位，不是最佳推断——真实冒烟里它被当推断展示过。"""
    from devprompt_ai.domain.decision.followup import build_unknowns

    facts = [FactResult("symbol_in_file", False, "未找到")]
    items = build_unknowns(_design_probe(), facts)

    assert items[0].best_guess == ""


def test_best_guess_prefers_available_evidence() -> None:
    from devprompt_ai.domain.decision.followup import build_unknowns

    facts = [
        FactResult("symbol_in_file", False, "未找到"),
        FactResult("token_defined", True, "src/tokens.css:1:--color-primary"),
    ]
    items = build_unknowns(_design_probe(), facts)

    assert items[0].best_guess == "src/tokens.css:1:--color-primary"


# ── reply 纯回答（2026-11-05，对齐 Tianshu 的「无动作回合」）────────────


class ReplyGenerator(FakeGenerator):
    """记录 answer 的上下文，返回固定正文。"""

    def __init__(self, text: str = "因为它引用的文件更少。") -> None:
        self.text = text
        self.contexts: list[Any] = []

    async def answer(self, ctx: Any) -> str:
        self.contexts.append(ctx)
        return self.text


def test_reply_is_terminal_action() -> None:
    """判定标准 1（类型层）：REPLY 必须是终态，执行后不再回 AGENTIC。"""
    assert AgentAction.REPLY in TERMINAL_ACTIONS


def test_next_action_prompt_lists_reply() -> None:
    """prompt 两处都要登记 reply，否则模型看不到这个动作。"""
    from devprompt_ai.decision.prompts import NEXT_ACTION_SYSTEM, NEXT_ACTION_USER

    assert "reply" in NEXT_ACTION_SYSTEM
    assert "reply" in NEXT_ACTION_USER


async def test_reply_is_terminal_and_produces_no_variants() -> None:
    """判定标准 1（行为层）：执行 reply 不产出方案、不改档位。"""
    gen = ReplyGenerator()
    svc, store = _service(ScriptedDecider(actions=[_action(AgentAction.REPLY)]), generator=gen)

    snap = await svc.optimize("local", "C:/proj", "为什么选 B?", request_id="r")

    session = next(iter(store.items.values()))
    assert snap.state == FlowState.DONE.value
    assert snap.reply_text == gen.text
    assert not session.data.get("variants")
    assert "level" not in session.data


async def test_reply_context_carries_previous_variants() -> None:
    """判定标准 2：回答能引用上一轮方案原文。"""
    gen = ReplyGenerator()
    svc, store = _service(ScriptedDecider(actions=[]), generator=gen)
    session = _probe_session(store, all_pass=True)
    session.state = FlowState.AGENTIC.value
    session.data["project_root"] = "C:/proj"
    session.data["turn_memory"] = {
        "sentence": "把按钮改主色",
        "variants": [{"title": "最小改动", "body": "只改颜色", "changes": [], "level": "B"}],
        "clarifications": {},
    }

    await svc._act_reply(session)

    assert "【B 档】最小改动" in gen.contexts[0].previous_variants


def test_summary_carries_reply() -> None:
    """判定标准 3：回答写入多轮摘要，下一轮可引用。"""
    from devprompt_ai.domain.context.build_context import TurnSummary, summary_from_turn

    summary = summary_from_turn({"reply_text": "因为它只动一个文件"})
    assert summary["reply"] == "因为它只动一个文件"

    rendered = TurnSummary(turn_id="t", turn_index=0, reply=str(summary["reply"])).render()
    assert "回答" in rendered


def test_render_ranking_summarizes_decision() -> None:
    """推荐判定要压成可读一段，否则回答「为什么选 B」没有依据。"""
    from devprompt_ai.service import _render_ranking

    text = _render_ranking(
        {
            "variant": "B",
            "gap": 0.18,
            "confidence": 0.72,
            "marked": True,
            "reason": "B 档适配度最高且明显领先",
            "fit": 0.81,
            "total": 0.78,
        }
    )

    assert "推荐档位 B" in text
    assert "是否标记推荐 是" in text
    assert "与次优差距 0.18" in text
    assert "判定理由 B 档适配度最高且明显领先" in text


def test_render_ranking_is_empty_without_decision() -> None:
    from devprompt_ai.service import _render_ranking

    assert _render_ranking(None) == ""
    assert _render_ranking({}) == ""


async def test_reply_context_carries_ranking() -> None:
    """判定标准补充：回答「为什么选 B」时上下文里必须有推荐判定。"""
    gen = ReplyGenerator()
    svc, store = _service(ScriptedDecider(actions=[]), generator=gen)
    session = _probe_session(store, all_pass=True)
    session.state = FlowState.AGENTIC.value
    session.data["project_root"] = "C:/proj"
    session.data["ranking"] = {
        "variant": "B",
        "gap": 0.18,
        "confidence": 0.72,
        "marked": True,
        "reason": "B 档适配度最高",
        "fit": 0.81,
        "total": 0.78,
    }

    await svc._act_reply(session)

    assert "推荐档位 B" in gen.contexts[0].ranking_summary


def test_render_ranking_includes_per_level_details() -> None:
    """解释「为什么没选 C」需要各档实际分数，不能只有被选中的那一档。"""
    from devprompt_ai.service import _render_ranking

    text = _render_ranking(
        {
            "variant": "B",
            "gap": 0.21,
            "confidence": 0.74,
            "marked": True,
            "reason": "差距超过硬阈值",
            "fit": 0.82,
            "total": 0.79,
        },
        {
            "A": {"fit": 0.40, "total": 0.40},
            "B": {"fit": 0.82, "total": 0.79},
            "C": {"fit": 0.61, "total": 0.61},
        },
    )

    assert "各档明细" in text
    assert "B 适配度 0.82" in text
    assert "C 适配度 0.61" in text


async def test_rank_and_mark_records_per_level_details() -> None:
    """逐档明细要落进 session.data，否则回答轮拿不到落选档的分数。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    session = _probe_session(store, all_pass=True)
    session.state = FlowState.AGENTIC.value
    session.data["project_root"] = "C:/proj"
    variants = [VariantDraft(title="t", body="b", changes=[], level=level) for level in ("A", "B")]

    await svc._rank_and_mark(session, variants)

    assert set(session.data["ranking_details"]) == {"A", "B"}
    assert "fit" in session.data["ranking_details"]["A"]


def _clarification_session(
    store: FakeStore,
    *,
    previous_target: Mapping[str, object],
    current_target: Mapping[str, object],
) -> FlowSession:
    session = FlowSession(
        session_id="s-clar",
        user_id="local",
        state=FlowState.AGENTIC.value,
        data={
            "clarifications": {"改哪个页面": "列表页"},
            "turn_memory": {"target": previous_target},
            "target": current_target,
        },
    )
    store.items[session.session_id] = session
    return session


def test_inherited_clarifications_kept_for_same_target() -> None:
    """目标没变 → 上一轮的答案继续有效（不再重复追问）。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    target = {"name": "SubmitButton", "path": "src/ui/button.tsx"}
    session = _clarification_session(store, previous_target=target, current_target=target)

    svc._validate_inherited_clarifications(session, "r1")

    assert session.data["clarifications"] == {"改哪个页面": "列表页"}
    assert "clarifications_invalidated" not in session.data


def test_inherited_clarifications_invalidated_when_target_changes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """目标变了 → 旧答案作废并留痕（只记 key 的 hash，不记原文）。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    session = _clarification_session(
        store,
        previous_target={"name": "SubmitButton", "path": "src/ui/button.tsx"},
        current_target={"name": "UserList", "path": "src/user/list.tsx"},
    )

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        svc._validate_inherited_clarifications(session, "r1")

    assert session.data["clarifications"] == {}
    assert session.data["clarifications_invalidated"] == 1
    record = next(
        r for r in caplog.records if r.getMessage() == "followup.clarifications_invalidated"
    )
    assert "改哪个页面" not in record.getMessage()


def test_undeclared_claims_keep_c_when_strict_off() -> None:
    """默认灰度关闭：空声明只披露不改档，避免一次性大量降档。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    session = _probe_session(store, all_pass=True)
    session.state = FlowState.AGENTIC.value
    session.data["level"] = "C"
    variants = [
        VariantDraft(title="t", body="b", changes=[], level=level) for level in ("A", "B", "C")
    ]

    svc._audit_claims(session, variants)

    assert session.data["level"] == "C"
    assert session.data["claim_report"]["undeclared"] is True
    assert session.data["claim_report"]["coverage"] == 0.0
    assert session.data["claim_report"]["summary"] == "未声明引用，证据链无法核对"


def test_claim_strict_downgrades_undeclared_c(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """claim_strict 打开：空声明 C 档降为 B 并留痕。"""
    svc, store = _service(ScriptedDecider(actions=[]))
    svc._cfg = svc._cfg.model_copy(update={"claim_strict": True})
    session = _probe_session(store, all_pass=True)
    session.state = FlowState.AGENTIC.value
    session.data["level"] = "C"
    variants = [
        VariantDraft(title="t", body="b", changes=[], level=level) for level in ("A", "B", "C")
    ]

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        svc._audit_claims(session, variants)

    assert session.data["level"] == "B"
    assert any(record.getMessage() == "evidence.claim_undeclared" for record in caplog.records)
