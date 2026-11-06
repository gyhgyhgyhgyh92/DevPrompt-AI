"""ForgeService 全流程测试（Fake 注入，无真实 I/O）。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from devprompt_ai.common.i18n import tr
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import (
    AskOption,
    AskQuestion,
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.errors import DevPromptError, StateError
from devprompt_ai.domain.generate.ports import MultiVariantDraft, VariantDraft
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    SessionSummary,
    Symbol,
    TurnRecord,
    TurnStore,
)
from devprompt_ai.domain.progress import ActionInfo, ProgressEvent, ProgressSink
from devprompt_ai.memory.turn_store import SQLiteTurnStore
from devprompt_ai.service import _RANK_CACHE, FlowSnapshot, ForgeService


@dataclass(slots=True)
class FakeStore:
    items: dict[str, FlowSession] = field(default_factory=dict)
    fail_save: bool = False

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        if self.fail_save:
            return False
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        out: list[SessionSummary] = []
        for s in self.items.values():
            if s.user_id != user_id:
                continue
            sentence = str(s.data.get("sentence", "")).strip()
            title = str(s.data.get("custom_title") or sentence[:40])
            out.append(
                SessionSummary(
                    session_id=s.session_id,
                    state=s.state,
                    project=str(s.data.get("project_root", "")),
                    updated_at="2026-10-12T00:00:00Z",
                    title=title,
                    pinned=bool(s.data.get("pinned", False)),
                )
            )
        out.sort(key=lambda s: (s.pinned, s.updated_at), reverse=True)
        return out[:limit]

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        targets = [
            sid
            for sid, s in self.items.items()
            if str(s.data.get("project_root", "")) == project_root
        ]
        for sid in targets:
            self.items.pop(sid, None)
        return len(targets)


class FakeDecider:
    """三方法全接（阶段五）：probe 可编程置信度，rank/score 带调用计数与异常注入。"""

    def __init__(
        self,
        confs: list[float],
        scores: dict[str, tuple[int, float]] | None = None,
        score_error: Exception | None = None,
        probe_error: Exception | None = None,
    ) -> None:
        self.confs = confs
        self.scores = scores or {"A": (2, 0.9), "B": (3, 0.9), "C": (4, 0.9)}
        self.score_error = score_error
        self.probe_error = probe_error
        self.rank_calls = 0
        self.score_calls = 0

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        if self.probe_error is not None:
            raise self.probe_error
        keys = [f.key for f in facts]
        judgments = [
            FactJudgment(key=k, passed=c >= 0.75, confidence=c)
            for k, c in zip(keys, self.confs, strict=False)
        ]
        # 反问时机由决策层给出（2026-10-20）：只对真实缺口提问，等价旧「失败即问」
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
        self.rank_calls += 1
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        self.score_calls += 1
        if self.score_error is not None:
            raise self.score_error
        return ScorePromptsOutput(
            scores=[
                VariantScore(
                    variant=cast(Literal["A", "B", "C"], key),
                    score=self.scores[key][0],
                    confidence=self.scores[key][1],
                )
                for key, _ in variants
            ]
        )


class FakeGenerator:
    async def generate_single(self, ctx):  # type: ignore[no-untyped-def]
        return VariantDraft(title="t", body="b", changes=["x"], level=ctx.level)

    async def generate_variants(self, ctx, levels):  # type: ignore[no-untyped-def]
        return MultiVariantDraft(
            variants=[VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels]
        )

    async def answer(self, ctx):  # type: ignore[no-untyped-def]
        return "回答"


class FakeRunner:
    """按 rg 参数内容路由：symbol/token/testid/states 查询各返回命中行。"""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str]] = [
            ("SubmitButton", "src/ui/button.tsx:12:SubmitButton"),
            ("--color-x", "src/styles/tokens.css:1:  --color-x: #3b82f6"),
            ("data-testid", "src/ui/button.tsx:14:  data-testid='s'"),
            (":hover", "src/ui/button.tsx:20:  .btn:hover"),
        ]

    async def run(self, args, **kw):  # type: ignore[no-untyped-def]
        for needle, out in self.routes:
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


class RecordingSink:
    """记录 progress 事件（流式端点的队列 sink 替身）。"""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[ActionInfo]:
        return [e.action for e in self.events if e.action is not None]


def _symbols() -> list[Symbol]:
    # 3 个符号：冻结 F-102 的 MIN_CANDIDATES=3 下，单符号必触发 manual_required，
    # 与「非 manual 全流程」用例意图冲突；SubmitButton 须排第一（同分时名字更短优先）。
    return [
        Symbol(name="SubmitButton", path="src/ui/button.tsx", line=12, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/ui/button_group.tsx", line=30, kind="function"),
        Symbol(name="SubmitForm", path="src/ui/form.tsx", line=8, kind="function"),
    ]


def _service(
    confs: list[float] | None = None,
    store: FakeStore | None = None,
    fail_save: bool = False,
    existing: set[str] | None = None,
    symbols: list[Symbol] | None = None,
    guard: int | None = None,
    decider: FakeDecider | None = None,
    turns: TurnStore | None = None,
) -> tuple[ForgeService, FakeStore]:
    from devprompt_ai.harness.process import SymbolTableProvider

    cfg = (
        AppConfig(_env_file=None, followup_soft_round_guard=guard)  # type: ignore[call-arg]
        if guard is not None
        else AppConfig(_env_file=None)  # type: ignore[call-arg]
    )
    st = store or FakeStore(fail_save=fail_save)
    svc = ForgeService(
        cfg=cfg,
        decider=decider or FakeDecider(confs or [0.9] * 7),
        sessions=st,
        runner=FakeRunner(),
        reader=FakeReader(existing if existing is not None else {"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=symbols if symbols is not None else _symbols(),
        turns=turns,
    )
    return svc, st


@pytest.fixture(autouse=True)
def _isolated_rank_cache() -> None:
    """模块级 rank 缓存按用例隔离，避免跨用例污染调用计数断言。"""
    _RANK_CACHE.clear()


async def test_delete_project_sessions_rejects_empty_project_root() -> None:
    """空 project_root 视为缺参（1001）：否则会连「无路径」旧会话一起删。"""
    svc, store = _service()
    with pytest.raises(DevPromptError) as exc:
        await svc.delete_project_sessions("local", "   ")
    assert exc.value.code == 1001
    assert store.items == {}


async def test_optimize_full_flow_with_questions() -> None:
    # 默认 existing 无测试文件 → test_file_exists=False → 1 个未知项
    svc, store = _service()
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "ask"
    assert [q.key for q in snap.questions] == ["请确认 test_file_exists"]
    snap2 = await svc.ask_followup(
        "local",
        snap.session_id,
        {"请确认 test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert snap2.status == "done"
    # B 档（有符号、取证未全过）→ 可输出档位 [A,B]；打分 B(3)>A(2)，d≈0.177∈[0.12,0.5)
    assert [v.level for v in snap2.variants] == ["A", "B"]
    assert snap2.ranking is not None
    assert snap2.ranking.variant == "B"
    assert snap2.ranking.marked is True
    assert snap2.ranking.reason == tr("ranking.conf_small_gap")
    assert 0.12 <= snap2.ranking.gap < 0.5


async def test_optimize_clean_flow_skips_asking() -> None:
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})  # 七项全过 → 零提问
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"  # unknowns 空 → 零提问（MUST-26 ①）
    assert [v.level for v in snap.variants] == ["A", "B", "C"]  # C 档 → 三套同调
    assert snap.ranking is not None


async def test_scan_project_rejects_missing_path(tmp_path: Any) -> None:
    """路径不存在必须带码 2001（而不是裸 500），前端才能给准确文案。"""
    svc, _ = _service()
    with pytest.raises(DevPromptError) as caught:
        await svc.scan_project(str(tmp_path / "not-here"))
    assert caught.value.code == 2001


async def test_scan_project_counts_empty_dir(tmp_path: Any) -> None:
    svc, _ = _service()
    result = await svc.scan_project(str(tmp_path))
    assert result["total_symbols"] == 0
    assert result["total_files"] == 0


async def test_done_appends_one_turn(tmp_path: Any) -> None:
    """DONE 后双写一条 turn（切片 1：读路径仍走 session.payload）。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "done"
    stored = await turns.list_for_session(snap.session_id)
    assert [turn.turn_index for turn in stored] == [0]
    assert stored[0].state == "DONE"
    assert stored[0].output  # 方案全文已落库
    assert stored[0].facts  # 取证件随轮次保存


async def test_ask_call_id_is_recorded() -> None:
    """AskUserQuestion 的 call_id 落会话，便于审计（不含原句，MUST-19）。"""

    class CallIdDecider(FakeDecider):
        async def probe_facts(self, sentence, facts, *, answered=None):  # type: ignore[no-untyped-def]
            probe = await super().probe_facts(sentence, facts, answered=answered)
            return probe.model_copy(update={"ask_call_id": "call-abc"})

    svc, store = _service(decider=CallIdDecider([0.9] * 7))
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "ask"
    assert store.items[snap.session_id].data["pending_tool_call"] == "call-abc"


async def test_second_turn_reuses_same_session(tmp_path: Any) -> None:
    """多轮：同一 session 内第二轮不新建会话，turn_index 递增。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    sentence1 = "把提交按钮改成 primary-500"
    sentence2 = "把提交按钮改成 primary-600 并加禁用态"
    first = await svc.optimize("local", ".", sentence1, request_id="r1")
    second = await svc.optimize(
        "local", ".", sentence2, request_id="r2", session_id=first.session_id
    )

    assert first.status == "done"
    assert second.session_id == first.session_id
    stored = await turns.list_for_session(first.session_id)
    assert [turn.turn_index for turn in stored] == [0, 1]
    assert stored[1].input == sentence2


async def test_duplicate_turn_index_rejected(tmp_path: Any) -> None:
    """唯一索引即乐观锁：同一 (session, index) 被占时重复提交返回 6001。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    first = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    # 人为占用下一轮的序号，模拟并发请求已抢到锁
    await turns.append(
        TurnRecord(
            turn_id="dup",
            session_id=first.session_id,
            turn_index=1,
            state="INIT",
            input="另一个并发请求",
        )
    )

    with pytest.raises(StateError) as caught:
        await svc.optimize(
            "local", ".", "把提交按钮改成 primary-600", request_id="r2", session_id=first.session_id
        )
    assert caught.value.code == 6001


async def test_second_turn_offers_single_variant(tmp_path: Any) -> None:
    """首轮三套（方向未定），第二轮收敛为单套且不算分差（MUST-28）。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    first = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    second = await svc.optimize(
        "local", ".", "把提交按钮改成 primary-600", request_id="r2", session_id=first.session_id
    )

    assert len(first.variants) == 3
    assert len(second.variants) == 1
    assert second.ranking is None


async def test_base_turn_id_continues_from_that_turn(tmp_path: Any) -> None:
    """以历史轮为基线新开一轮：历史轮一条不少，基线轮的方案作为起点。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    first = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    base_id = str(first.current_turn_id)

    continued = await svc.optimize(
        "local",
        ".",
        "把提交按钮改成 primary-600",
        request_id="r2",
        session_id=first.session_id,
        base_turn_id=base_id,
    )

    assert continued.state in {"DONE", "ASKING"}
    # 历史轮一条不少（turn 表 append-only，MUST-32）
    stored = await turns.list_for_session(first.session_id)
    assert len(stored) == 2
    assert stored[0].turn_id == base_id


async def test_base_turn_id_of_other_session_raises_6003(tmp_path: Any) -> None:
    """基线轮不属于本用户 → 归属校验拒绝（6003）。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    first = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    with pytest.raises(StateError):
        await svc.optimize(
            "local",
            ".",
            "再改一次",
            request_id="r2",
            session_id=first.session_id,
            base_turn_id="turn-does-not-exist",
        )


async def test_direction_conflict_reopens_three_variants(tmp_path: Any) -> None:
    """用户表达方向性分歧时，第二轮重新展开三套。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, turns=turns)

    first = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    second = await svc.optimize(
        "local",
        ".",
        "推翻刚才的方案，换个方向重做提交按钮",
        request_id="r2",
        session_id=first.session_id,
    )

    assert len(second.variants) == 3


async def test_cannot_start_turn_while_previous_running(tmp_path: Any) -> None:
    """上一轮还在反问（ASKING）时不允许开新一轮。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(turns=turns)

    first = await svc.optimize("local", ".", "第一轮", request_id="r1")
    assert first.status == "ask"

    with pytest.raises(StateError) as caught:
        await svc.optimize("local", ".", "第二轮", request_id="r2", session_id=first.session_id)
    assert caught.value.code == 6001


async def test_unknown_session_on_optimize_raises_6003(tmp_path: Any) -> None:
    svc, _ = _service(turns=SQLiteTurnStore(str(tmp_path / "turns.db")))
    with pytest.raises(StateError) as caught:
        await svc.optimize("local", ".", "x", request_id="r1", session_id="missing")
    assert caught.value.code == 6003


async def test_ask_turn_is_recorded_in_asking_state(tmp_path: Any) -> None:
    """反问分支也落一轮（state=ASKING），历史页才能显示「第 N 轮 · 进行中」。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(turns=turns)

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "ask"
    stored = await turns.list_for_session(snap.session_id)
    assert [turn.state for turn in stored] == ["ASKING"]


async def test_turn_write_failure_does_not_break_flow(tmp_path: Any) -> None:
    """双写是旁路：存储故障不得让已完成的流程失败。"""

    class ExplodingTurns(SQLiteTurnStore):
        async def append(self, turn: Any) -> None:
            raise RuntimeError("disk full")

    svc, _ = _service(
        existing={"src/ui/button.tsx", "src/ui/button.test.tsx"},
        turns=ExplodingTurns(str(tmp_path / "turns.db")),
    )

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "done"


async def test_progress_events_carry_phase() -> None:
    """思考事件必须带阶段标签，前端才能把过程挂到对应步骤下（2026-10-20）。"""
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    sink = RecordingSink()

    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1", progress=sink)

    phases = [event.phase for event in sink.events if event.text]
    assert "RETRIEVING" in phases
    assert "GENERATING" in phases
    assert all(
        phase in {"INIT", "RETRIEVING", "PROBING", "ASKING", "CONFIRMING", "GENERATING", "RANKING"}
        for phase in phases
    )


async def test_progress_reports_real_tool_actions() -> None:
    """流式请求要把真实的 rg / 读文件上报成卡片，且详情不含项目绝对路径（MUST-19）。"""
    svc, _ = _service()
    sink = RecordingSink()

    await svc.optimize(
        "local", "D:/proj", "把提交按钮改成 primary-500", request_id="r1", progress=sink
    )

    actions = sink.actions()
    assert actions, "流式请求必须上报动作卡片"
    assert all("D:/proj" not in action.detail for action in actions)
    assert all("route-key" not in action.detail for action in actions)
    titles = {action.title for action in actions}
    assert "读取文件" in titles
    assert titles & {"检索符号", "定位符号定义"}


async def test_escape_rounds_to_conservative() -> None:
    svc, _ = _service(confs=[0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9])
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    done = await svc.escape("local", snap.session_id, request_id="r2")
    assert done.status == "done"
    assert [v.level for v in done.variants] == ["A"]  # 保守路径仅 A 档
    assert done.ranking is None  # MUST-28：单套不产生推荐视图


async def test_guardrail_rounds_then_confirm() -> None:
    # 默认 existing 无测试文件 → test_file_exists 持续未知；答复为空（跳过）→ unknowns 不消
    svc, _ = _service(guard=2)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    assert snap.status == "ask"
    snap = await svc.ask_followup("local", snap.session_id, {}, request_id="r2")
    assert snap.status == "ask"  # rounds=1 < 2
    snap = await svc.ask_followup("local", snap.session_id, {}, request_id="r3")
    assert snap.status == "guardrail"  # rounds=2 ≥ 2 → 显式裁决（非静默终止）
    snap = await svc.guardrail_confirm("local", snap.session_id, proceed=True, request_id="r4")
    assert snap.status == "ask"  # 裁决继续 → 清零再问（轮数无上限）


async def test_manual_required_path() -> None:
    svc, _ = _service(symbols=[])  # 空符号表 → manual_required 直达反问
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    assert snap.status == "ask" and snap.questions[0].key == "manual_target"
    done = await svc.ask_followup(
        "local",
        snap.session_id,
        {"manual_target": "SubmitButton@src/ui/button.tsx"},
        request_id="r2",
    )
    assert done.status == "done"


# ---- F-603/F-503 feedback 接入 L3（开放决策 #1 定稿合成语义）----


async def test_missing_session_raises_6003() -> None:
    svc, _ = _service()
    with pytest.raises(StateError) as ei:
        await svc.ask_followup("local", "nope", {}, request_id="r")
    assert ei.value.code == 6003


async def test_wrong_state_raises_6001() -> None:
    svc, store = _service()
    snap = await svc.optimize("local", ".", "改", request_id="r1")
    store.items[snap.session_id].state = "DONE"
    with pytest.raises(StateError) as ei:
        await svc.ask_followup("local", snap.session_id, {}, request_id="r2")
    assert ei.value.code == 6001


class RecordingStore(FakeStore):
    """记录每次 save 时的状态值，用于断言状态机真实流转路径（MUST-07 唯一状态机）。"""

    def __init__(self) -> None:
        super().__init__()
        self.states: list[str] = []

    async def save(self, session: FlowSession) -> bool:
        self.states.append(session.state)
        return await super().save(session)


async def test_three_variants_flow_passes_ranking_state() -> None:
    # 七项全过 → C 档三套 → 状态机必须经停 RANKING（GENERATING→RANKING→DONE）
    store = RecordingStore()
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, store=store)
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert "RANKING" in store.states
    assert (
        store.states.index("GENERATING")
        < store.states.index("RANKING")
        < store.states.index("DONE")
    )


async def test_single_variant_skips_score_prompts() -> None:
    # escape 保守路径 level=A → 单套：不调用 score_prompts、ranking=None、不计算 d（MUST-28）
    decider = FakeDecider([0.9] * 7)
    svc, _ = _service(decider=decider)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    done = await svc.escape("local", snap.session_id, request_id="r2")
    assert done.status == "done" and done.ranking is None
    assert decider.score_calls == 0


async def test_score_prompts_failure_degrades_without_blocking() -> None:
    # 打分异常 → 诚实降级 ranking=None，流程仍走完 DONE（不阻断、不崩溃）
    decider = FakeDecider([0.9] * 7, score_error=RuntimeError("LLM unavailable"))
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, decider=decider)
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done" and snap.state == "DONE"
    assert len(snap.variants) == 3
    assert snap.ranking is None
    assert decider.score_calls == 1


async def test_rank_components_cache_hits_on_same_input() -> None:
    # 同项目+同原句+同阈值配置 → 二次 optimize 命中模块级缓存，mock 只跑一次（MUST-14）
    decider = FakeDecider([0.9] * 7)
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, decider=decider)
    sentence = "缓存命中专用：把提交按钮改成 primary-500 cache-probe-42"
    await svc.optimize("local", ".", sentence, request_id="r1")
    assert decider.rank_calls == 1
    await svc.optimize("local", ".", sentence, request_id="r2")
    assert decider.rank_calls == 1


async def test_snapshot_carries_target_and_facts() -> None:
    """上下文面板数据源（设计 §1.2）：快照只读透出目标定位与取证事实（additive 契约）。"""
    svc, _ = _service()
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.target is not None
    assert snap.target.name == "SubmitButton"
    assert snap.target.path == "src/ui/button.tsx"
    assert snap.target.line == 12
    assert snap.facts  # 取证事实非空
    assert all(f.key and f.evidence for f in snap.facts)


async def test_list_history_returns_summaries() -> None:
    """GET /history 转正：会话摘要脱敏（title 为原句截断，MUST-19 修订后允许）。"""
    svc, _ = _service()
    await svc.optimize("local", "/tmp/demo-proj", "改提交按钮", request_id="r1")
    items = (await svc.list_history("local")).items
    assert len(items) == 1
    assert items[0].state in {"ASKING", "DONE"}
    assert items[0].project == "/tmp/demo-proj"  # FakeStore 摘要直传；真实 store 取 basename
    assert items[0].title == "改提交按钮"  # 无 custom_title → 原句截断（≤40）
    assert items[0].pinned is False


async def test_update_settings_writes_applies_and_masks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-604：模型段落设置文件（0600）、流程段落 app_settings；回显脱敏；运行配置即时生效。"""
    import json
    import os
    import stat

    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    view = await svc.update_settings(
        {
            "model_service": {"base_url": "https://api.x", "api_key": "sk-plain-1234567890"},
            "process": {"followup_soft_round_guard": 7, "telemetry": False},
        }
    )
    # 回显恒脱敏（MUST-19），明文不出现在视图
    assert view["model_service"]["api_key_masked"] == "sk-••••7890"
    assert "sk-plain-1234567890" not in str(view)
    # 明文只进设置文件（0600，POSIX；Windows 无权限位），不入 SQLite
    import os as _os

    if _os.name != "nt":
        assert stat.S_IMODE(os.stat(settings_file).st_mode) == 0o600
    doc = json.loads(settings_file.read_text(encoding="utf-8"))
    assert doc["model_service"]["api_key"] == "sk-plain-1234567890"
    assert "sk-plain" not in (tmp_path / "settings.db").read_text(encoding="utf-8", errors="ignore")
    # 运行配置即时生效（含进程参数）
    assert svc._cfg.llm_base_url == "https://api.x"
    assert svc._cfg.followup_soft_round_guard == 7
    assert svc._cfg.telemetry is False
    # 锁定项恒 25（MUST-09），不接受修改
    assert view["locked"]["candidate_limit"] == 25

    # 空 api_key = 保持不变
    view2 = await svc.update_settings({"model_service": {"api_key": ""}})
    assert view2["model_service"]["api_key_masked"] == "sk-••••7890"


async def test_flow_events_chain_without_sentence(caplog: pytest.LogCaptureFixture) -> None:
    """T6-9：一次完整流程可查链路事件（flow.started/completed 等），且 INFO 级不落原句。"""
    import logging as _logging

    svc, _ = _service()
    sentence = "把提交按钮改成 primary-500"
    with caplog.at_level(_logging.INFO, logger="devprompt.events"):
        snap = await svc.optimize("local", ".", sentence, request_id="r1")
        if snap.status == "ask":
            await svc.ask_followup(
                "local", snap.session_id, {"请确认 test_file_exists": "已确认"}, request_id="r2"
            )
    names = [r.getMessage() for r in caplog.records]
    assert "flow.started" in names
    assert "flow.completed" in names
    assert "cache.miss" in names or "cache.hit" in names
    assert any(n.startswith("recommendation.") for n in names)
    completed = next(r for r in caplog.records if r.getMessage() == "flow.completed")
    assert getattr(completed, "flow_id", "") != ""
    assert isinstance(getattr(completed, "elapsed_ms", None), int)
    # MUST-19：事件字段与消息均不得携带用户原句
    for r in caplog.records:
        assert sentence not in r.getMessage()
        for key, value in vars(r).items():
            if key not in {"msg", "args", "message", "asctime"}:
                assert sentence not in str(value)


# ---------- 6G 遗留①失败兜底 + D-6F-4 清空 + 供应商标识 ----------


async def test_failed_optimize_aborts_session() -> None:
    """6G 遗留①：失败请求不残留死会话——异常路径置 ABORTED（如 PROBING 挂起不再出现）。"""
    svc, store = _service(decider=FakeDecider([0.9] * 7, probe_error=RuntimeError("llm down")))
    with pytest.raises(RuntimeError, match="llm down"):
        await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    sessions = list(store.items.values())
    assert len(sessions) == 1
    assert sessions[0].state == "ABORTED"  # 不残留 PROBING


async def test_failed_ask_followup_aborts_session() -> None:
    """6G 遗留①同类：答复路径失败同样兜底 ABORTED，异常照常冒泡。"""
    svc, store = _service()
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "ask"

    async def _boom(session: FlowSession, *, progress: ProgressSink | None = None) -> FlowSnapshot:
        raise RuntimeError("reprobe down")

    svc._reprobe = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="reprobe down"):
        await svc.ask_followup(
            "local", snap.session_id, {"请确认 test_file_exists": "x"}, request_id="r2"
        )
    assert store.items[snap.session_id].state == "ABORTED"


def test_suppress_ask_requires_execution_and_complete_evidence() -> None:
    """信息充足闸门（2026-11-03）：执行类 + 七项取证全过才抑制；设计类保留深挖。"""
    svc, _ = _service()
    ask = AskQuestion(
        key="",
        question="红色的落地方式选哪种?",
        header="方案",
        options=[AskOption(label="新增主题变量", description="改设计变量层")],
    )
    execution = FactProbeOutput(
        judgments=[], overall_confidence=0.0, questions=[ask], task_kind="execution"
    )
    design = execution.model_copy(update={"task_kind": "design"})
    passed = FactResult(key="target_file_exists", passed=True, evidence="x")
    failed = FactResult(key="symbol_in_file", passed=False, evidence="y")

    assert svc._suppress_ask(execution, [passed]) is True
    assert svc._suppress_ask(execution, [passed, failed]) is False
    assert svc._suppress_ask(execution, []) is False
    assert svc._suppress_ask(design, [passed]) is False


async def test_ask_suppressed_when_evidence_complete() -> None:
    """模型仍想提问、但取证已全过且是执行类：不打断流程，记 suppressed 计数（MUST-19 不记原文）。"""

    class _AskAnyway(FakeDecider):
        async def probe_facts(self, sentence, facts, *, answered=None):  # type: ignore[no-untyped-def]
            probe = await super().probe_facts(sentence, facts, answered=answered)
            return probe.model_copy(
                update={
                    "questions": [
                        AskQuestion(
                            key="",
                            question="红色的落地方式选哪种?",
                            header="方案",
                            options=[AskOption(label="新增主题变量", description="改变量层")],
                        )
                    ]
                }
            )

    svc, store = _service(
        decider=_AskAnyway([0.9] * 7),
        existing={"src/ui/button.tsx", "src/ui/button.test.tsx"},
    )
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.status == "done"
    assert store.items[snap.session_id].data["suppressed_questions"] == 1
    assert store.items[snap.session_id].data["unknowns"] == []


async def test_update_settings_carries_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """遗留④：供应商标识为契约字段——写入设置文件并经加载链生效，GET 回读一致。"""
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    view = await svc.update_settings({"model_service": {"provider": "DeepSeek"}})
    assert view["model_service"]["provider"] == "DeepSeek"
    assert svc._cfg.llm_provider == "DeepSeek"  # 运行配置即时生效
    # 落盘并经加载链回读（新构造 AppConfig 同值）
    from devprompt_ai.memory.settings_store import read_model_settings

    assert read_model_settings()["provider"] == "DeepSeek"
    reloaded = AppConfig(_env_file=None)  # type: ignore[call-arg]
    assert reloaded.llm_provider == "DeepSeek"


# ---------- 多模型注册表（F-604，2026-10-13） ----------


async def test_settings_models_registry_roundtrip_and_activation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """整表写入 + 激活整条生效：视图脱敏/is_active 正确；激活后运行配置与落盘镜像该条目。

    2026-10-18 供应商中心化：端点与密钥改由 `provider_configs` 提供，条目只引用。
    """
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    view = await svc.update_settings(
        {
            "provider_configs": [
                {
                    "id": "p-a",
                    "provider": "DeepSeek",
                    "base_url": "https://a.example",
                    "api_key": "sk-aaaa-1234567890",
                },
                {
                    "id": "p-b",
                    "provider": "OpenAI 兼容",
                    "base_url": "https://b.example",
                    "api_key": "sk-bbbb-1234567890",
                },
            ],
            "models": [
                {"provider_id": "p-a", "model_id": "deepseek-flash"},
                {"provider_id": "p-b", "model_id": "gpt-x"},
            ],
            "active_model_id": "",
        }
    )
    assert len(view["models"]) == 2
    assert all(m["is_active"] is False for m in view["models"])  # 未指定激活位
    assert view["provider_configs"][0]["api_key_masked"] == "sk-••••7890"
    assert "sk-aaaa-1234567890" not in str(view)  # 回显恒脱敏（MUST-19）

    first_id = view["models"][0]["id"]
    assert first_id.startswith("m-")  # 后端生成 id

    # 激活第二条：整条生效（base_url/api_key/model_id 全部镜像进运行配置）
    second_id = view["models"][1]["id"]
    view2 = await svc.update_settings({"active_model_id": second_id})
    active = [m for m in view2["models"] if m["is_active"]]
    assert [m["id"] for m in active] == [second_id]
    assert svc._cfg.llm_base_url == "https://b.example"
    assert svc._cfg.llm_model == "gpt-x"
    assert svc._cfg.llm_api_key == "sk-bbbb-1234567890"
    from devprompt_ai.memory.settings_store import read_model_settings

    assert read_model_settings()["model_id"] == "gpt-x"  # 镜像已落盘


async def test_settings_provider_delete_cascades_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """删除供应商 → 其下条目一并消失（用户裁定的级联语义）。"""
    from devprompt_ai.memory.settings_store import read_model_registry

    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    await svc.update_settings(
        {
            "provider_configs": [
                {"id": "p-a", "provider": "DeepSeek", "base_url": "https://a", "api_key": "sk-a"},
                {"id": "p-b", "provider": "DeepSeek", "base_url": "https://b", "api_key": "sk-b"},
            ],
            "models": [
                {"provider_id": "p-a", "model_id": "deepseek-flash"},
                {"provider_id": "p-b", "model_id": "deepseek-v4-pro"},
            ],
        }
    )
    assert len(read_model_registry()["models"]) == 2

    # 权威列表里去掉 p-b → 供应商与其条目都被删除
    view = await svc.update_settings(
        {
            "provider_configs": [
                {"id": "p-a", "provider": "DeepSeek", "base_url": "https://a", "api_key": ""}
            ],
            "models": [{"provider_id": "p-a", "model_id": "deepseek-flash"}],
        }
    )
    assert [r["id"] for r in view["provider_configs"]] == ["p-a"]
    assert [m["model_id"] for m in view["models"]] == ["deepseek-flash"]


async def test_settings_models_api_key_retention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同 id 供应商 api_key 留空=沿用旧密钥（2026-10-18 起密钥只存供应商段）。"""
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    view = await svc.update_settings(
        {
            "provider_configs": [
                {
                    "id": "p-1",
                    "provider": "DeepSeek",
                    "base_url": "https://a.example",
                    "api_key": "sk-keep-1234567890",
                }
            ],
            "models": [{"provider_id": "p-1", "model_id": "deepseek-chat"}],
        }
    )
    entry = view["models"][0]
    assert entry["model_id"] == "deepseek-chat"
    assert view["provider_configs"][0]["api_key_masked"] == "sk-••••7890"

    # 第二次整表替换：同 id 且 api_key 为空 → 密钥保留
    view2 = await svc.update_settings(
        {
            "provider_configs": [
                {
                    "id": "p-1",
                    "provider": "DeepSeek",
                    "base_url": "https://a2.example",
                    "api_key": "",
                }
            ],
            "models": [{"id": entry["id"], "provider_id": "p-1", "model_id": "deepseek-chat"}],
        }
    )
    assert view2["provider_configs"][0]["base_url"] == "https://a2.example"
    assert view2["provider_configs"][0]["api_key_masked"] == "sk-••••7890"


async def test_settings_empty_registry_leaves_model_service_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """零回归：注册表为空且无激活位时，不触碰既有 model_service 配置。"""
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", str(tmp_path / "settings.db"))
    svc, _ = _service()

    await svc.update_settings({"model_service": {"base_url": "https://keep.example"}})
    view = await svc.update_settings({"models": []})
    assert view["models"] == []
    assert svc._cfg.llm_base_url == "https://keep.example"


# ---------- Task 1：Web 会话管理（rename/pin/delete，T1.3） ----------


class FailNextStore(FakeStore):
    """可编程注入 CAS 冲突：fail_next>0 时后续 save 返回 False（用后自减）。"""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next = 0
        self.attempts = 0

    async def save(self, session: FlowSession) -> bool:
        self.attempts += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            return False
        return await super().save(session)


async def test_rename_session_sets_custom_title() -> None:
    """PATCH 重命名：strip 后写 custom_title，list_history 的 title 取自定义值（优先原句）。"""
    svc, store = _service()
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await svc.rename_session("local", snap.session_id, "  我的新标题  ")
    assert store.items[snap.session_id].data["custom_title"] == "我的新标题"  # strip
    items = (await svc.list_history("local")).items
    assert items[0].title == "我的新标题"


async def test_rename_session_truncates_to_80() -> None:
    svc, store = _service()
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await svc.rename_session("local", snap.session_id, "x" * 100)
    assert len(store.items[snap.session_id].data["custom_title"]) == 80


async def test_pin_session_sets_flag_and_orders_first() -> None:
    """PATCH 置顶：pinned 落 payload，且置顶项排在同侪之前（list_history 排序）。"""
    svc, store = _service()
    first = await svc.optimize("local", ".", "第一个会话", request_id="r1")
    await svc.optimize("local", ".", "第二个会话", request_id="r2")
    await svc.pin_session("local", first.session_id, True)
    items = (await svc.list_history("local")).items
    assert store.items[first.session_id].data["pinned"] is True
    assert items[0].session_id == first.session_id
    assert items[0].pinned is True


async def test_session_management_missing_raises_6003() -> None:
    svc, _ = _service()
    for coro in (
        svc.rename_session("local", "nope", "t"),
        svc.pin_session("local", "nope", True),
        svc.delete_session("local", "nope"),
    ):
        with pytest.raises(StateError) as ei:
            await coro
        assert ei.value.code == 6003


async def test_session_management_wrong_owner_raises_6003() -> None:
    svc, store = _service()
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    store.items[snap.session_id].user_id = "other"
    with pytest.raises(StateError) as ei:
        await svc.rename_session("local", snap.session_id, "t")
    assert ei.value.code == 6003


async def test_delete_session_removes() -> None:
    svc, store = _service()
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await svc.delete_session("local", snap.session_id)
    assert snap.session_id not in store.items
    assert (await svc.list_history("local")).items == ()


async def test_rename_session_retries_cas_once() -> None:
    """MUST-11：首次 CAS 失败 → 重载取新版本重试成功。"""
    store = FailNextStore()
    svc, _ = _service(store=store)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    store.fail_next = 1  # 仅注入一次冲突，避免影响 optimize 期间的正常转移
    before = store.attempts
    await svc.rename_session("local", snap.session_id, "重试标题")
    assert store.attempts == before + 2  # 首次失败 + 重试成功
    assert store.items[snap.session_id].data["custom_title"] == "重试标题"


async def test_rename_session_cas_conflict_twice_raises_6003() -> None:
    """首次 + 重试均冲突（fail_next=2）→ 抛 6003（不无限重试）。"""
    store = FailNextStore()
    svc, _ = _service(store=store)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    store.fail_next = 2
    with pytest.raises(StateError) as ei:
        await svc.rename_session("local", snap.session_id, "t")
    assert ei.value.code == 6003


async def test_resume_tolerates_legacy_ranking_with_pref() -> None:
    """2026-10-31 体检回归：偏好记忆移除前落库的会话 ranking 仍带 pref 字段。

    重建快照必须按字段白名单过滤，否则 RankingView(**data) 抛 TypeError，
    历史会话在 GET /result 上整体 500（用户升级后旧会话全部打不开）。
    """
    svc, store = _service()
    store.items["legacy-1"] = FlowSession(
        session_id="legacy-1",
        user_id="local",
        state="DONE",
        data={
            "variants": [{"title": "方案A", "body": "b", "changes": [], "level": "A"}],
            "ranking": {
                "variant": "B",
                "gap": 0.2,
                "confidence": 0.8,
                "marked": True,
                "reason": "适配度领先",
                "fit": 0.75,
                "total": 0.75,
                "pref": 0.6,  # 2026-10-21 已移除的字段，旧数据里仍在
            },
        },
    )

    snap = await svc.resume("local", "legacy-1", request_id="r-legacy")

    assert snap.status == "done"
    assert snap.ranking is not None
    assert (snap.ranking.variant, snap.ranking.fit, snap.ranking.total) == ("B", 0.75, 0.75)


async def test_snapshot_carries_current_turn_id(tmp_path: Any) -> None:
    """多轮归属（2026-11-04）：快照带本轮 turn id，前端据此决定谁进历史列表、谁进对话区。"""
    turns = SQLiteTurnStore(str(tmp_path / "turns.db"))
    svc, _ = _service(turns=turns)

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    records = (await svc.list_turns("local", snap.session_id)).items
    assert len(records) == 1
    assert snap.current_turn_id == records[0].turn_id


async def test_snapshot_current_turn_id_none_without_turn_store() -> None:
    """无 turn 存储时归属为 None：前端保留原行为，不会误判。"""
    svc, _ = _service()

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.current_turn_id is None
