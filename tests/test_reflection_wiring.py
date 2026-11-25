"""Reflection 接线测试（2026-11-22）：召回注入与收尾写入的端到端连接。

用 FakeReflection 替身（不联网）验证三件事：
1. 召回结果经 ``_assemble_context`` → ``GenerationContext.reflection_block`` 抵达生成层；
2. turn 收尾同时写「项目 / 全局」两个桶，且全局桶不带 target/paths；
3. 未启用（reflection=None）时区块恒为空串，行为与改造前一致。
"""

from __future__ import annotations

import logging

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import AskOption, AskQuestion
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.domain.reflection.port import (
    ReflectionHit,
    ReflectionNote,
    ReflectionPort,
    ReflectionScope,
)
from devprompt_ai.service import ForgeService
from test_service import (
    FakeDecider,
    FakeGenerator,
    FakeReader,
    FakeRunner,
    FakeStore,
    _symbols,
)


class RecordingGenerator(FakeGenerator):
    """记录每次生成的上下文，供断言区块内容。"""

    def __init__(self) -> None:
        self.contexts: list[GenerationContext] = []

    async def generate_single(
        self, ctx: GenerationContext, locale: str = "zh-CN", *, fallback: bool = False
    ) -> VariantDraft:
        self.contexts.append(ctx)
        return VariantDraft(title="t", body="b", changes=["x"], fallback=fallback)


class FakeReflection:
    """固定召回一条项目经验，并记录所有写入的 note。"""

    def __init__(self) -> None:
        self.notes: list[ReflectionNote] = []

    async def recall(
        self, *, sentence: str, domain: str, project_root: str
    ) -> tuple[ReflectionHit, ...]:
        return (ReflectionHit(scope=ReflectionScope.PROJECT, text="此仓库用 pnpm", score=1.0),)

    async def record(self, note: ReflectionNote) -> bool:
        self.notes.append(note)
        return True


def _service_with_reflection(
    gen: RecordingGenerator,
    reflection: ReflectionPort | None,
    decider: FakeDecider | None = None,
    reader: FakeReader | None = None,
) -> ForgeService:
    from devprompt_ai.harness.process import SymbolTableProvider

    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=decider or FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=reader or FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
        reflection=reflection,
    )


async def test_recall_block_reaches_generation_context() -> None:
    gen = RecordingGenerator()
    svc = _service_with_reflection(gen, FakeReflection())

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert snap.state == "DONE"
    assert gen.contexts, "生成确已发生"
    block = gen.contexts[0].reflection_block
    assert "此仓库用 pnpm" in block
    assert "历史经验" in block
    assert "- [项目]" in block


async def test_turn_writes_both_buckets_and_global_has_no_paths() -> None:
    gen = RecordingGenerator()
    fake = FakeReflection()
    svc = _service_with_reflection(gen, fake)

    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    scopes = [note.scope for note in fake.notes]
    assert ReflectionScope.PROJECT in scopes
    assert ReflectionScope.GLOBAL in scopes
    global_note = next(note for note in fake.notes if note.scope is ReflectionScope.GLOBAL)
    assert global_note.paths == ()
    assert global_note.target == ""


async def test_disabled_reflection_keeps_block_empty() -> None:
    gen = RecordingGenerator()
    svc = _service_with_reflection(gen, None)

    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    assert gen.contexts, "生成确已发生"
    assert all(ctx.reflection_block == "" for ctx in gen.contexts)


class OptionDecider(FakeDecider):
    """前两次各问一个带选项的问题，第三次不再提问，让流程走到 DONE。"""

    def __init__(self) -> None:
        super().__init__([0.1] * 7)
        self.probes = 0

    async def probe_facts(self, sentence, facts, *, answered=None):  # type: ignore[no-untyped-def]
        self.probes += 1
        base = await super().probe_facts(sentence, facts, answered=answered)
        if self.probes == 1:
            question = AskQuestion(
                key="scope",
                question="改动范围选哪种？",
                header="改动范围",
                options=[AskOption(label="最小改动"), AskOption(label="激进改版")],
                best_guess="最小改动",
            )
            return base.model_copy(update={"questions": [question]})
        if self.probes == 2:
            question = AskQuestion(
                key="plan",
                question="方案选哪种？",
                header="方案",
                options=[AskOption(label="最小改动"), AskOption(label="激进改版")],
                best_guess="最小改动",
            )
            return base.model_copy(update={"questions": [question]})
        return base.model_copy(update={"questions": []})


async def test_clarification_preferences_reach_notes() -> None:
    gen = RecordingGenerator()
    fake = FakeReflection()
    svc = _service_with_reflection(
        gen,
        fake,
        OptionDecider(),
        FakeReader({"src/ui/button.tsx"}),
    )

    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "ask"
    snap = await svc.ask_followup(
        "local", snap.session_id, {"改动范围选哪种？": "最小改动"}, request_id="r2"
    )
    assert snap.status == "ask"
    snap = await svc.ask_followup(
        "local", snap.session_id, {"方案选哪种？": "最小改动"}, request_id="r3"
    )
    assert snap.status == "done"

    project = [note for note in fake.notes if note.scope is ReflectionScope.PROJECT][-1]
    global_ = [note for note in fake.notes if note.scope is ReflectionScope.GLOBAL][-1]
    assert "回答方式：点选项 2/2" in project.summary
    assert "回答风格：偏好点选项（2/2）" in global_.summary
    assert "最小改动" not in global_.summary
    assert "改动范围" not in global_.summary
    assert project.stop_reason == "natural-finish"


def _signal(header: str = "改动范围") -> dict[str, object]:
    return {
        "key": "改动范围选哪种？",
        "header": header,
        "kind": "option",
        "labels": ["最小改动"],
        "tendencies": ["最小改动"],
        "answer_chars": 4,
        "short": True,
        "decisive": False,
        "multi_select": False,
        "round_index": 1,
    }


def test_reflection_notes_keep_option_detail_project_only() -> None:
    svc = _service_with_reflection(RecordingGenerator(), None)
    session = FlowSession(
        session_id="s-pref",
        user_id="local",
        state="DONE",
        data={
            "sentence": "改按钮",
            "project_root": ".",
            "stop_reason": "natural-finish",
            "clarification_signals": [_signal(), _signal()],
        },
    )

    project, global_ = svc._reflection_notes(session)

    assert "回答偏好：改动范围=最小改动（2/2）" in project.summary
    assert "决策倾向：最小改动（2/2）" in project.summary
    assert "回答风格：偏好点选项（2/2）" in global_.summary
    assert "最小改动" not in global_.summary
    assert "改动范围" not in global_.summary


async def test_done_turn_records_natural_finish() -> None:
    fake = FakeReflection()
    svc = _service_with_reflection(RecordingGenerator(), fake)

    await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")

    project = [note for note in fake.notes if note.scope is ReflectionScope.PROJECT][-1]
    assert project.stop_reason == "natural-finish"


def test_capture_answer_signals_emits_counts_only(caplog) -> None:  # type: ignore[no-untyped-def]
    svc = _service_with_reflection(RecordingGenerator(), FakeReflection())
    session = FlowSession(
        session_id="s-capture",
        user_id="local",
        state="ASKING",
        data={
            "rounds": 1,
            "unknowns": [
                {
                    "key": "改动范围选哪种？",
                    "header": "改动范围",
                    "best_guess": "最小改动",
                    "multi_select": False,
                    "options": [
                        {"label": "最小改动", "description": "只动当前文件"},
                        {"label": "激进改版", "description": "一并重构"},
                    ],
                }
            ],
        },
    )

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        svc._capture_answer_signals(session, {"改动范围选哪种？": "最小改动"})

    stored = session.data["clarification_signals"]
    assert len(stored) == 1
    assert stored[0]["kind"] == "option"
    record = next(
        item for item in caplog.records if item.getMessage() == "clarification.answer_classified"
    )
    assert record.total == 1
    assert record.option == 1
    assert record.free_text == 0
    assert "最小改动" not in str(record.__dict__)


def test_reflection_disabled_skips_preference_capture(caplog) -> None:  # type: ignore[no-untyped-def]
    svc = _service_with_reflection(RecordingGenerator(), None)
    session = FlowSession(
        session_id="s-off",
        user_id="local",
        state="ASKING",
        data={"rounds": 1, "unknowns": [{"key": "q", "options": [{"label": "最小改动"}]}]},
    )

    with caplog.at_level(logging.INFO, logger="devprompt.events"):
        svc._capture_answer_signals(session, {"q": "最小改动"})

    assert "clarification_signals" not in session.data
    assert not any(
        item.getMessage() == "clarification.answer_classified" for item in caplog.records
    )
