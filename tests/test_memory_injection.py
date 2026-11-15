"""6G 三层记忆逐层关闭验证（T6-8 / D-6G-3）。

判定口径（D-6G-3）：记忆关闭导致的**行为退化**（如重复提问、生成上下文缺失该层）
属预期行为非缺陷；仅当流程**失败**（未到 DONE / 未捕获异常）才判 FAIL。
注入模式沿用 tests/test_service.py 的 FakeStore / FakeDecider /
FakeGenerator（无真实 I/O）。
"""

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.generate.ports import (
    GeneratePort,
    GenerationContext,
    VariantDraft,
)
from devprompt_ai.memory.project_notes import read_notes
from devprompt_ai.service import ForgeService
from test_service import (
    FakeDecider,
    FakeGenerator,
    FakeReader,
    FakeRunner,
    FakeStore,
    _service,
    _symbols,
)


class RecordingGenerator(FakeGenerator):
    """捕获 GenerationContext：断言 L2 缺失时生成上下文不含项目记忆层且不崩溃。"""

    def __init__(self) -> None:
        self.contexts: list[GenerationContext] = []

    async def generate_single(  # type: ignore[no-untyped-def]
        self, ctx: GenerationContext, locale: str = "zh-CN", *, fallback: bool = False
    ) -> VariantDraft:
        self.contexts.append(ctx)
        return VariantDraft(title="t", body="b", changes=["x"], fallback=fallback)


def _service_with_generator(gen: GeneratePort, existing: set[str]) -> ForgeService:
    from devprompt_ai.harness.process import SymbolTableProvider

    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader(existing),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    return svc


async def test_l1_session_memory_off_fresh_session_completes() -> None:
    """L1 会话记忆关闭：全新会话无 clarifications 记忆，全流程 optimize→生成仍到达 DONE。

    可接受退化（不判 FAIL）：无 L1 记忆时第二个全新会话会重复问同一未知项（D-6G-3）。
    """
    svc, store = _service(existing={"src/ui/button.tsx"})  # 缺测试文件 → 有未知项需澄清
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert store.items[snap.session_id].data["clarifications"] == {}  # L1 记忆为空
    assert snap.status == "ask"
    done = await svc.ask_followup(
        "local",
        snap.session_id,
        {"请确认 test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert done.status == "done"
    assert done.state == "DONE"
    assert done.variant is not None  # 生成产出非空

    # 退化验证：无跨会话 L1 记忆 → 同一未知项被重复提问（行为退化非缺陷，流程仍可完成）
    svc2, _ = _service(existing={"src/ui/button.tsx"})
    snap2 = await svc2.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r3")
    assert snap2.status == "ask"
    assert [q.key for q in snap2.questions] == [q.key for q in snap.questions]  # 重复提问
    done2 = await svc2.ask_followup(
        "local",
        snap2.session_id,
        {"请确认 test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r4",
    )
    assert done2.status == "done" and done2.state == "DONE"


async def test_l2_project_notes_off_flow_completes() -> None:
    """L2 项目 notes 关闭：notes 为空/缺失时流程完成，生成上下文缺失该层不崩溃。"""
    # 层关闭注入：FakeRunner 对 git notes 命令无路由 → 空输出 = 无 notes
    assert await read_notes("C:/repo", FakeRunner()) == []

    gen = RecordingGenerator()
    svc = _service_with_generator(gen, existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.state == "DONE"
    assert snap.variant is not None

    # 压缩骨架语义（MUST-09 精神）：只有摘要与记忆块，不含 L2 note 正文。
    # 2026-10-20 多轮：新增 history_block / memory_block 两个装配结果字段。
    assert gen.contexts  # 生成确已发生
    for ctx in gen.contexts:
        dumped = ctx.model_dump()
        assert set(dumped) == {
            "sentence",
            "project_root",
            "facts_summary",
            "clarifications",
            "conservative",
            "history_block",
            "memory_block",
            # 2026-11-04 多轮继承：上一轮方案正文（迭代轮引用，首轮为空串）
            "previous_variants",
            # 2026-11-05 推荐依据：回答「为什么选 B」时必须看到判定结果
            "ranking_summary",
            # 2026-11-11 四段式方案的两路证据（代码片段 / 设计令牌）
            "target_excerpt",
            "design_tokens",
            # 2026-11-14 领域包
            "domain_id",
            # 2026-11-14 多模态：visual 域风格与图生图参考图（其余域恒为空缺省）
            "style_id",
            "images",
        }
        assert dumped["clarifications"] == {}
        assert "note" not in dumped["memory_block"]


async def test_context_delta_is_full_on_first_turn_and_incremental_after() -> None:
    """B1–B4：首轮下发完整 `<context-update>`，后续轮只发变动块（无变动自闭合）。"""
    gen = RecordingGenerator()
    svc = _service_with_generator(gen, existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert 'mode="full"' in gen.contexts[0].history_block

    await svc.optimize(
        "local", ".", "把提交按钮改成 primary-600", session_id=snap.session_id, request_id="r2"
    )
    second = gen.contexts[-1].history_block
    assert 'mode="full"' not in second, "第二轮不得重发完整上下文"
    assert '<context-update seq="2"' in second, "seq 必须跨轮递增"


async def test_single_variant_output_stable_under_neutral_memory() -> None:
    """补充：三层全关（无 L1/L2、中性 L3）叠加时单套输出契约仍成立。"""
    gen = RecordingGenerator()
    svc = _service_with_generator(gen, existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.variant is not None
    assert snap.variant.fallback is False
    assert gen.contexts and gen.contexts[0].clarifications == {}
