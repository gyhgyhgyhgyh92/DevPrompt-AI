"""Reflection 接线测试（2026-11-22）：召回注入与收尾写入的端到端连接。

用 FakeReflection 替身（不联网）验证三件事：
1. 召回结果经 ``_assemble_context`` → ``GenerationContext.reflection_block`` 抵达生成层；
2. turn 收尾同时写「项目 / 全局」两个桶，且全局桶不带 target/paths；
3. 未启用（reflection=None）时区块恒为空串，行为与改造前一致。
"""

from __future__ import annotations

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft
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
    gen: RecordingGenerator, reflection: ReflectionPort | None
) -> ForgeService:
    from devprompt_ai.harness.process import SymbolTableProvider

    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader({"src/ui/button.tsx", "src/ui/button.test.tsx"}),
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
