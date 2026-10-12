"""6G 三层记忆逐层关闭验证（T6-8 / D-6G-3）。

判定口径（D-6G-3）：记忆关闭导致的**行为退化**（如重复提问、生成上下文缺失该层）
属预期行为非缺陷；仅当流程**失败**（未到 DONE / 未捕获异常）才判 FAIL。
注入模式沿用 tests/test_service.py 的 FakeStore / FakePreferenceStore / FakeDecider /
FakeGenerator（无真实 I/O）。
"""

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.generate.ports import (
    GeneratePort,
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.domain.ranking.preference import INITIAL_PREFERENCE
from devprompt_ai.memory.project_notes import read_notes
from devprompt_ai.service import ForgeService
from test_service import (
    FakeDecider,
    FakeGenerator,
    FakePreferenceStore,
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

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level]
    ) -> MultiVariantDraft:
        self.contexts.append(ctx)
        return MultiVariantDraft(
            variants=[VariantDraft(title="t", body="b", changes=["x"], level=lv) for lv in levels]
        )


def _service_with_generator(
    gen: GeneratePort, existing: set[str]
) -> tuple[ForgeService, FakePreferenceStore]:
    from devprompt_ai.harness.process import SymbolTableProvider

    prefs = FakePreferenceStore()
    svc = ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=FakeDecider([0.9] * 7),
        sessions=FakeStore(),
        preferences=prefs,
        runner=FakeRunner(),
        reader=FakeReader(existing),
        generator=gen,
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )
    return svc, prefs


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
        {"test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r2",
    )
    assert done.status == "done"
    assert done.state == "DONE"
    assert done.variants  # 生成产出非空

    # 退化验证：无跨会话 L1 记忆 → 同一未知项被重复提问（行为退化非缺陷，流程仍可完成）
    svc2, _ = _service(existing={"src/ui/button.tsx"})
    snap2 = await svc2.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r3")
    assert snap2.status == "ask"
    assert [q.key for q in snap2.questions] == [q.key for q in snap.questions]  # 重复提问
    done2 = await svc2.ask_followup(
        "local",
        snap2.session_id,
        {"test_file_exists": "新增 src/ui/button.test.tsx"},
        request_id="r4",
    )
    assert done2.status == "done" and done2.state == "DONE"


async def test_l2_project_notes_off_flow_completes() -> None:
    """L2 项目 notes 关闭：notes 为空/缺失时流程完成，生成上下文缺失该层不崩溃。"""
    # 层关闭注入：FakeRunner 对 git notes 命令无路由 → 空输出 = 无 notes
    assert await read_notes("C:/repo", FakeRunner()) == []

    gen = RecordingGenerator()
    svc, _ = _service_with_generator(gen, existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    assert snap.state == "DONE"
    assert snap.variants

    # 生成上下文缺失 L2 层：无项目记忆字段、无 note 正文混入（压缩骨架语义，MUST-09 精神）
    assert gen.contexts  # 生成确已发生
    for ctx in gen.contexts:
        dumped = ctx.model_dump()
        assert set(dumped) == {
            "sentence",
            "project_root",
            "level",
            "facts_summary",
            "clarifications",
            "conservative",
        }
        assert dumped["clarifications"] == {}


async def test_l3_preference_neutral_flow_completes() -> None:
    """L3 偏好关闭：中性向量（全初始值）下流程完成，推荐仍由后端判定不异常。"""
    prefs = FakePreferenceStore()  # 无任何记录 → load 返回 INITIAL_PREFERENCE 中性向量
    svc, _ = _service(
        existing={"src/ui/button.tsx", "src/ui/button.test.tsx"},
        prefs=prefs,
    )
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done" and snap.state == "DONE"
    assert [v.level for v in snap.variants] == ["A", "B", "C"]

    # 推荐仍由后端判定：ranking 正常产出（MUST-27/28 唯一判定位置），无异常
    assert snap.ranking is not None
    assert snap.ranking.variant in {"A", "B", "C"}
    assert snap.ranking.marked in (True, False)
    if not snap.ranking.marked:
        assert snap.ranking.reason  # 不标也必须给具体原因（MUST-27 诚实策略）

    # 中性偏好未被流程污染（无反馈不动 L3）
    assert await svc.get_preference("local") == INITIAL_PREFERENCE

    # 「按规则不标」分支：仅 A 档（逃生保守路径）→ 跳过打分，ranking=None（MUST-28）
    svc2, _ = _service(existing={"src/ui/button.tsx"}, prefs=FakePreferenceStore())
    snap2 = await svc2.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r3")
    assert snap2.status == "ask"
    done = await svc2.escape("local", snap2.session_id, request_id="r4")
    assert done.status == "done" and done.state == "DONE"
    assert done.ranking is None


async def test_multi_variant_draft_level_sets_stable_under_neutral_memory() -> None:
    """补充：三层全关（无 L1/L2、中性 L3）叠加时生成契约仍成立（MUST-28 前缀集）。"""
    gen = RecordingGenerator()
    svc, _ = _service_with_generator(gen, existing={"src/ui/button.tsx", "src/ui/button.test.tsx"})
    snap = await svc.optimize("local", ".", "把提交按钮改成 primary-500", request_id="r1")
    assert snap.status == "done"
    multi = MultiVariantDraft(variants=snap.variants)
    assert [v.level for v in multi.variants] == ["A", "B", "C"]
    assert gen.contexts and gen.contexts[0].clarifications == {}
