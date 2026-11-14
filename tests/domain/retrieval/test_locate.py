"""F-103 全文定位测试。"""

from fakes import FakeCommandRunner, FakeFileReader

from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.locate import _pick_anchor_line, locate_symbol

_SYM = Symbol(name="SubmitButton", path="src/ui/Button.tsx", line=12, kind="function")

_RG_DEF = "\n".join(
    [
        '{"type":"match","data":{"path":{"text":"src/ui/Button.tsx"},"line_number":12,"submatches":[{"match":{"text":"SubmitButton"}}]}}',  # noqa: E501
    ]
)
_FILE = """
export function SubmitButton() {
  return <button className="btn btn--submit" data-testid="submit-btn">提交</button>
}
/* token: --color-primary-500 */
"""

_ROUTES = {
    ("rg", "def:SubmitButton"): _RG_DEF,
    ("rg", "tok:src/ui/Button.tsx"): "src/ui/Button.tsx:5:  --color-primary-500",
    ("rg", "test:Button"): "src/ui/Button.test.tsx",
}


async def test_definition_search_runs_from_project_root() -> None:
    """rg 必须以项目根为 cwd：进程 cwd 是本工具仓库，`--glob 相对路径` 否则永不命中。

    真实故障（2026-10-19）：不传 cwd 时定义行号恒为 0、七项取证集体「未找到」，
    用户在反问卡里看到 5 个无从回答的未知项。
    """
    runner = FakeCommandRunner(_ROUTES)
    # root 非 "." 时读文件要拼绝对路径（FileReader 侧的正确行为，本次不变）
    reader = FakeFileReader({"D:/proj/src/ui/Button.tsx": _FILE})

    await locate_symbol(_SYM, runner, reader, root="D:/proj")

    # 2026-11-11：设计令牌探测（design-tokens）是第二次 rg，同样必须以项目根为 cwd。
    assert runner.cwds == ["D:/proj", "D:/proj"]


async def test_locate_returns_definition_selectors_tokens_tests() -> None:
    runner = FakeCommandRunner(_ROUTES)
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE, "src/ui/Button.test.tsx": "it works"})
    loc = await locate_symbol(_SYM, runner, reader)
    assert loc.definition_line == 12
    assert "btn" in loc.selectors and "btn--submit" in loc.selectors
    assert "--color-primary-500" in loc.tokens
    assert loc.test_paths == ["src/ui/Button.test.tsx"]


_TWO_BUTTONS = "\n".join(
    [
        "export function Page() {",  # 1
        "  const a = 1",  # 2
        "  const b = 2",  # 3
        "  const c = 3",  # 4
        "  return (",  # 5
        '    <Button type="primary" onClick={openAdd}>新增图书</Button>',  # 6
        "  )",  # 7
        "}",  # 8
        "function renderOps(record) {",  # 9
        "  const d = 4",  # 10
        "  return (",  # 11
        '    <Button type="link" onClick={() => openEdit(record)}>',  # 12
        "      编辑",  # 13
        "    </Button>",  # 14
        "  )",  # 15
        "}",  # 16
    ]
)


def test_anchor_prefers_current_sentence_over_previous() -> None:
    """多轮：本轮句优先，且多行 JSX 也要能锚到（2026-11-12）。"""
    # 本轮说「编辑按钮」，上一轮说「新增图书」→ 必须锚到第 11~12 行的编辑按钮块
    anchor = _pick_anchor_line(
        _TWO_BUTTONS, 1, "把本页面的编辑按钮改为橙色", "把新增图书按钮改为红色"
    )
    assert anchor in (11, 12)


def test_anchor_falls_back_to_merged_when_current_is_weak() -> None:
    """本轮句只写「把这个改一下」时，退回「本轮 ∪ 上一轮」并锚到上一轮那处。"""
    # 窗口打分会取到目标行前 2 行作为锚点起点，片段仍覆盖第 6 行
    assert _pick_anchor_line(_TWO_BUTTONS, 1, "把这个改一下", "把新增图书按钮改为红色") in (
        4,
        5,
        6,
    )


_FILTER_BAR_THEN_TARGET = "\n".join(
    [
        "export function Page() {",  # 1
        "  const search = 1",  # 2
        "  return (",  # 3
        "    <>",  # 4
        "      <Space size={8}>",  # 5
        '        <Button type="primary" onClick={handleSearch}>查询</Button>',  # 6
        "        <Button onClick={handleReset}>重置</Button>",  # 7
        "      </Space>",  # 8
        "      <PageContainer",  # 9
        "        extra={",  # 10
        '          <Button type="primary" danger onClick={openAdd}>',  # 11
        "            新增图书",  # 12
        "          </Button>",  # 13
        "        }",  # 14
        "      />",  # 15
        "    </>",  # 16
        "  )",  # 17
        "}",  # 18
    ]
)


def test_anchor_generic_only_current_sentence_falls_back_to_merged() -> None:
    """本轮句只命中泛化词（button/click/size）时不得锁定无关按钮（实测 R2 场景）。

    旧判据会锚到筛选区的「查询」按钮（5~7 行），片段里没有「新增图书」那一行；
    合并上一轮「新增图书按钮」后才能锚到真正的目标（11 行附近）。
    """
    anchor = _pick_anchor_line(
        _FILTER_BAR_THEN_TARGET,
        1,
        "在上一轮的基础上，把这个按钮的红色改成橙色（warning），保留原有图标和尺寸",
        "把新增图书按钮改为红色",
    )
    assert anchor >= 10, anchor


async def test_vue_file_probes_brand_token() -> None:
    """令牌探测覆盖 .vue 与 brand 命名族（2026-11-12 扩面）。"""
    sym = Symbol(name="BookCard", path="src/components/BookCard.vue", line=3, kind="function")
    builder = "\n".join(
        [
            "<template>",
            '  <div class="card">{{ title }}</div>',  # 2
            "</template>",
            "<style>",
            ".card { color: var(--brand-500); }",
            "</style>",
        ]
    )
    runner = FakeCommandRunner(
        {
            ("rg", "def:BookCard"): (
                '{"type":"match","data":{"path":{"text":"src/components/BookCard.vue"},'
                '"line_number":3,"submatches":[{"match":{"text":"BookCard"}}]}}'
            ),
            ("rg", "design-tokens"): "src/styles/brand.css:12:  --brand-500: #ff4d4f;",
        }
    )
    reader = FakeFileReader({sym.path: builder})

    loc = await locate_symbol(sym, runner, reader, sentence="把卡片主色改为品牌红")

    assert any("--brand-500" in hit for hit in loc.token_hits)
    token_args = next(a for a in runner.calls if "--route-key=design-tokens" in a)
    glob_index = token_args.index("--glob")
    assert "vue" in token_args[glob_index + 1]
