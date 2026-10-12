"""ForgeService 全流程测试（Fake 注入，无真实 I/O）。"""

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import (
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.generate.ports import MultiVariantDraft, VariantDraft
from devprompt_ai.domain.models import Candidate, FactResult, FlowSession, SessionSummary, Symbol
from devprompt_ai.domain.ranking.ports import AdoptionRecord
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.domain.ranking.recommend import REASON_SMALL_GAP
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

    async def list_recent(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
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

    async def probe_facts(self, sentence: str, facts: list[FactResult]) -> FactProbeOutput:
        if self.probe_error is not None:
            raise self.probe_error
        keys = [f.key for f in facts]
        return FactProbeOutput(
            judgments=[
                FactJudgment(key=k, passed=c >= 0.75, confidence=c)
                for k, c in zip(keys, self.confs, strict=False)
            ],
            overall_confidence=sum(self.confs) / len(self.confs) if self.confs else 0.0,
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


class FakePreferenceStore:
    """内存偏好存储（PreferenceStore 最小实现，无 I/O）；fail=True 模拟存储故障。"""

    def __init__(self, fail: bool = False) -> None:
        self.vectors: dict[str, dict[str, float]] = {}
        self.records: list[AdoptionRecord] = []
        self.fail = fail

    async def load(self, user_id: str) -> dict[str, float]:
        if self.fail:
            raise RuntimeError("preference store unavailable")
        v = self.vectors.get(user_id)
        return dict(v) if v is not None else dict(INITIAL_PREFERENCE)

    async def save(self, user_id: str, vector: dict[str, float]) -> None:
        if self.fail:
            raise RuntimeError("preference store unavailable")
        self.vectors[user_id] = dict(vector)

    async def record_adoption(self, rec: AdoptionRecord) -> None:
        if self.fail:
            raise RuntimeError("preference store unavailable")
        self.records.append(rec)

    async def clear_adoptions(self, user_id: str) -> int:
        if self.fail:
            raise RuntimeError("preference store unavailable")
        before = len(self.records)
        self.records = [r for r in self.records if r.user_id != user_id]
        return before - len(self.records)


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
    prefs: FakePreferenceStore | None = None,
    decider: FakeDecider | None = None,
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
        preferences=FakePreferenceStore() if prefs is None else prefs,
        runner=FakeRunner(),
        reader=FakeReader(existing if existing is not None else {"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=symbols if symbols is not None else _symbols(),
    )
    return svc, st


@pytest.fixture(autouse=True)
def _isolated_rank_cache() -> None:
    """模块级 rank 缓存按用例隔离，避免跨用例污染调用计数断言。"""
    _RANK_CACHE.clear()


async def test_optimize_full_flow_with_questions() -> None:
    # 默认 existing 无测试文件 → test_file_exists=False → 1 个未知项
    svc, store = _service()
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "ask"
    assert [q.key for q in snap.questions] == ["test_file_exists"]
    snap2 = await svc.ask_followup(
        "local",
        snap.session_id,
        {"test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert snap2.status == "done"
    # B 档（有符号、取证未全过）→ 可输出档位 [A,B]；打分 B(3)>A(2)，d≈0.177∈[0.12,0.5)
    assert [v.level for v in snap2.variants] == ["A", "B"]
    assert snap2.ranking is not None
    assert snap2.ranking.variant == "B"
    assert snap2.ranking.marked is True
    assert snap2.ranking.reason == REASON_SMALL_GAP
    assert 0.12 <= snap2.ranking.gap < 0.5


async def test_optimize_clean_flow_skips_asking() -> None:
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})  # 七项全过 → 零提问
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"  # unknowns 空 → 零提问（MUST-26 ①）
    assert [v.level for v in snap.variants] == ["A", "B", "C"]  # C 档 → 三套同调
    assert snap.ranking is not None


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


async def test_feedback_adoption_updates_l3_vector() -> None:
    prefs = FakePreferenceStore()
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, prefs=prefs)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    assert snap.status == "done"
    await svc.feedback("local", snap.session_id, "accept", variant="C", request_id="r2")
    pref = await svc.get_preference("local")
    # EMA 10% 步进：0.5 + 0.1×(0.9−0.5) = 0.54；max_files_norm: 0.5 + 0.1×(1.0−0.5) = 0.55
    assert pref["detail_level"] == pytest.approx(0.54, abs=1e-9)
    assert pref["max_files_norm"] == pytest.approx(0.55, abs=1e-9)
    assert len(prefs.records) == 1  # 采纳历史入库（F-503 adoption_history）
    assert prefs.records[0].variant == "C" and prefs.records[0].edited is False


async def test_feedback_edited_adoption_weaker_than_direct() -> None:
    # 会话 variant body="b"（FakeGenerator）；编辑稿 "b!!!" → 相似度 0.4 → 占比 0.6 → 强度 0.4
    direct_svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    direct = await direct_svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await direct_svc.feedback("local", direct.session_id, "accept", variant="C", request_id="r2")
    pref_direct = await direct_svc.get_preference("local")

    edited_svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    edited = await edited_svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await edited_svc.feedback(
        "local", edited.session_id, "accept", variant="C", edited_text="b!!!", request_id="r2"
    )
    pref_edited = await edited_svc.get_preference("local")

    assert 0.5 < pref_edited["detail_level"] < pref_direct["detail_level"]  # 同向但弱于直接采纳
    sim = difflib.SequenceMatcher(None, "b", "b!!!").ratio()  # 相似度 0.4 → 占比 0.6 → 强度 0.4
    assert pref_edited["detail_level"] == pytest.approx(
        0.5 + 0.1 * (1 - (1 - sim)) * (0.9 - 0.5),
        abs=1e-9,  # 强度 = 1 − 占比 = sim
    )


async def test_feedback_skip_regresses_toward_neutral() -> None:
    prefs = FakePreferenceStore()
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, prefs=prefs)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await svc.feedback("local", snap.session_id, "accept", variant="C", request_id="r2")
    await svc.feedback("local", snap.session_id, "skip", request_id="r3")  # 两者皆无 = 跳过
    pref = await svc.get_preference("local")
    # 0.54 + (0.5−0.54)×0.3 = 0.528（开放决策 #1：趋向中性，独立规则不经 EMA）
    assert pref["detail_level"] == pytest.approx(0.528, abs=1e-9)
    assert len(prefs.records) == 1  # 跳过无采纳，不追加历史


async def test_feedback_unknown_variant_raises() -> None:
    svc, _ = _service()
    bad: str = "X"  # 故意传入非法档位：服务层运行时防线（HTTP 层契约校验前的最后闸门）
    with pytest.raises(ValueError, match="未知方案档位"):
        await svc.feedback(
            "local",
            "s1",
            "accept",
            variant=bad,  # type: ignore[arg-type]  # 故意违约：服务层运行时防线
            request_id="r1",
        )


async def test_feedback_store_failure_swallowed() -> None:
    prefs = FakePreferenceStore(fail=True)
    svc, _ = _service(prefs=prefs)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    await svc.feedback("local", snap.session_id, "accept", variant="C", request_id="r2")  # 不上抛
    await svc.feedback("local", snap.session_id, "skip", request_id="r3")  # 不上抛


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


async def test_get_preference_initial_vector() -> None:
    svc, _ = _service()
    pref = await svc.get_preference("local")
    assert pref == {
        "detail_level": 0.5,
        "include_diff": 0.5,
        "specify_tests": 0.5,
        "max_files_norm": 0.5,
    }


# ---- 5F：RANKING 编排 / 降级 / 缓存（阶段五）----


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


async def test_feedback_edited_full_chain_updates_vector() -> None:
    # 全链：clean 流程三套 → feedback(accept, variant, edited_text) → L3 向量按强度移动
    prefs = FakePreferenceStore()
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"}, prefs=prefs)
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    assert [v.level for v in snap.variants] == ["A", "B", "C"]
    await svc.feedback(
        "local", snap.session_id, "accept", variant="C", edited_text="b!!!", request_id="r2"
    )
    pref = await svc.get_preference("local")
    sim = difflib.SequenceMatcher(None, "b", "b!!!").ratio()  # 0.4 → 占比 0.6 → 强度 0.4
    assert pref["detail_level"] == pytest.approx(0.5 + 0.1 * sim * (0.9 - 0.5), abs=1e-9)
    assert len(prefs.records) == 1
    assert prefs.records[0].variant == "C" and prefs.records[0].edited is True


# ---------- T6-11 转正与 F-604 设置（6A） ----------


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


async def test_set_preference_clips_out_of_range() -> None:
    """PUT /preference 转正：部分更新 + clip01（超界截断而非拒绝），未知维度快速失败。"""
    svc, _ = _service()
    updated = await svc.set_preference("local", {"detail_level": 1.5, "specify_tests": -0.2})
    assert updated["detail_level"] == 1.0  # 超上界截断
    assert updated["specify_tests"] == 0.0  # 超下界截断
    assert updated["include_diff"] == 0.5  # 未提及维度保持
    with pytest.raises(ValueError, match="未知偏好维度"):
        await svc.set_preference("local", {"nope": 0.5})


async def test_list_history_returns_summaries() -> None:
    """GET /history 转正：会话摘要脱敏（title 为原句截断，MUST-19 修订后允许）。"""
    svc, _ = _service()
    await svc.optimize("local", "/tmp/demo-proj", "改提交按钮", request_id="r1")
    items = await svc.list_history("local")
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
                "local", snap.session_id, {"test_file_exists": "已确认"}, request_id="r2"
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

    async def _boom(session: FlowSession) -> FlowSnapshot:
        raise RuntimeError("reprobe down")

    svc._reprobe = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="reprobe down"):
        await svc.ask_followup("local", snap.session_id, {"test_file_exists": "x"}, request_id="r2")
    assert store.items[snap.session_id].state == "ABORTED"


async def test_clear_adoption_history_only_own_records() -> None:
    """D-6F-4：服务端清空采纳历史——仅本用户分区，返回清空条数，向量不动。"""
    prefs = FakePreferenceStore()
    svc, _ = _service(prefs=prefs)
    await svc.feedback("local", "s1", "accept", variant="B", request_id="r1")
    await svc.feedback("local", "s2", "accept", variant="C", request_id="r2")
    await svc.feedback("other", "s3", "accept", variant="A", request_id="r3")
    before = await svc.get_preference("local")

    cleared = await svc.clear_adoption_history("local")
    assert cleared == 2
    assert [r.user_id for r in prefs.records] == ["other"]  # 他人分区不受影响
    assert await svc.get_preference("local") == before  # 偏好向量不动
    assert await svc.clear_adoption_history("local") == 0  # 幂等：再次清空 0 条


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
    items = await svc.list_history("local")
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
    items = await svc.list_history("local")
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
    assert await svc.list_history("local") == []


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


# ---------- 原生文件夹选择器（POST /project/pick） ----------


async def test_pick_project_folder_returns_existing_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """选择成功：后端校验「存在且为目录」后返回绝对路径（用户裁定强度）。"""
    import devprompt_ai.service as service_module

    picked = str(tmp_path)

    async def _fake_pick() -> str:
        return picked

    monkeypatch.setattr(service_module, "pick_folder_dialog", _fake_pick)
    svc, _ = _service()
    assert await svc.pick_project_folder() == picked


async def test_pick_project_folder_cancel_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户取消对话框：空串原样返回（前端据此保持原选择、不报错）。"""
    import devprompt_ai.service as service_module

    async def _fake_pick() -> str:
        return ""

    monkeypatch.setattr(service_module, "pick_folder_dialog", _fake_pick)
    svc, _ = _service()
    assert await svc.pick_project_folder() == ""


async def test_pick_project_folder_invalid_dir_raises_2001(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """非目录（MUST-20 防线）：抛 RetrievalError 2001，错误消息不含路径本体（MUST-19）。"""
    import devprompt_ai.service as service_module
    from devprompt_ai.domain.errors import RetrievalError

    missing = str(tmp_path / "not-exist-dir")

    async def _fake_pick() -> str:
        return missing

    monkeypatch.setattr(service_module, "pick_folder_dialog", _fake_pick)
    svc, _ = _service()
    with pytest.raises(RetrievalError) as err:
        await svc.pick_project_folder()
    assert err.value.code == 2001
    assert missing not in str(err.value)
