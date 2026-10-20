"""F-103 全文定位测试。"""

from fakes import FakeCommandRunner, FakeFileReader

from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.locate import locate_symbol

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

    assert runner.cwds == ["D:/proj"]


async def test_locate_returns_definition_selectors_tokens_tests() -> None:
    runner = FakeCommandRunner(_ROUTES)
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE, "src/ui/Button.test.tsx": "it works"})
    loc = await locate_symbol(_SYM, runner, reader)
    assert loc.definition_line == 12
    assert "btn" in loc.selectors and "btn--submit" in loc.selectors
    assert "--color-primary-500" in loc.tokens
    assert loc.test_paths == ["src/ui/Button.test.tsx"]
