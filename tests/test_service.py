"""ForgeService 全流程测试（Fake 注入，无真实 I/O）。"""

import difflib
from dataclasses import dataclass, field

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import FactJudgment, FactProbeOutput
from devprompt_ai.domain.errors import StateError
from devprompt_ai.domain.generate.ports import MultiVariantDraft, VariantDraft
from devprompt_ai.domain.models import FlowSession, Symbol
from devprompt_ai.domain.ranking.ports import AdoptionRecord
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.service import ForgeService


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


class FakeDecider:
    """probe_facts 可编程；rank/score 阶段五。"""

    def __init__(self, confs: list[float]) -> None:
        self.confs = confs

    async def probe_facts(self, sentence: str, facts):  # type: ignore[no-untyped-def]
        keys = [f.key for f in facts]
        return FactProbeOutput(
            judgments=[
                FactJudgment(key=k, passed=c >= 0.75, confidence=c)
                for k, c in zip(keys, self.confs, strict=False)
            ],
            overall_confidence=sum(self.confs) / len(self.confs) if self.confs else 0.0,
        )

    async def rank_components(self, sentence, candidates): ...  # type: ignore[no-untyped-def]

    async def score_prompts(self, context, variants): ...  # type: ignore[no-untyped-def]


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
        decider=FakeDecider(confs or [0.9] * 7),
        sessions=st,
        preferences=FakePreferenceStore() if prefs is None else prefs,
        runner=FakeRunner(),
        reader=FakeReader(existing if existing is not None else {"src/ui/button.tsx"}),
        generator=FakeGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=symbols if symbols is not None else _symbols(),
    )
    return svc, st


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
    assert snap2.variant is not None and snap2.variant.level in ("A", "B", "C")


async def test_optimize_clean_flow_skips_asking() -> None:
    svc, _ = _service(existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})  # 七项全过 → 零提问
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"  # unknowns 空 → 零提问（MUST-26 ①）


async def test_escape_rounds_to_conservative() -> None:
    svc, _ = _service(confs=[0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9])
    snap = await svc.optimize("local", ".", "改提交按钮", request_id="r1")
    done = await svc.escape("local", snap.session_id, request_id="r2")
    assert done.status == "done" and done.variant is not None and done.variant.level == "A"


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
