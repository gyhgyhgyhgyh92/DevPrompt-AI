"""F-104 七项事实测试：每项含真/假分支，证据非「未知」。"""

from fakes import FakeCommandRunner, FakeFileReader

from devprompt_ai.domain.models import CodeLocation, FactKey, FactResult
from devprompt_ai.domain.retrieval.facts import (
    is_evidence_complete,
    is_probe_complete,
    verify_facts,
)

_LOC_TRUE = CodeLocation(
    symbol_name="SubmitButton",
    path="src/ui/Button.tsx",
    definition_line=12,
    selectors=["btn", "btn--submit"],
    tokens=["--color-primary-500"],
    test_paths=["src/ui/Button.test.tsx"],
)
_FILE = 'export const SubmitButton = () => <button data-testid="s" className="btn btn:hover" />'
_TOKEN_DEF = "src/styles/tokens.css:1:  --color-primary-500: #3b82f6"


def _routes(
    token_defined: bool, token_source: str = "src/styles/tokens.css"
) -> dict[tuple[str, str], str]:
    r: dict[tuple[str, str], str] = {
        ("rg", "symbol:src/ui/Button.tsx"): "src/ui/Button.tsx:1:  export const SubmitButton",
        ("rg", "testid:src/ui/Button.tsx"): 'src/ui/Button.tsx:1:  data-testid="s"',
        ("rg", "states:src/ui/Button.tsx"): "src/ui/Button.tsx:1:  btn:hover",
        ("rg", "tokdef:--color-primary-500"): _TOKEN_DEF if token_defined else "",
    }
    return r


async def _verify(
    loc: CodeLocation, reader: FakeFileReader, routes: dict[tuple[str, str], str]
) -> dict[FactKey, str]:
    runner = FakeCommandRunner(routes)
    results = await verify_facts(loc, "把提交按钮改为 primary-500", runner, reader)
    return {r.key: ("pass" if r.passed else "fail") for r in results}


async def test_rg_runs_from_project_root() -> None:
    """四条 rg 都必须以项目根为 cwd（2026-10-19 真实故障：不传 cwd 时全部「未找到」）。"""
    reader = FakeFileReader(
        {"src/ui/Button.tsx": _FILE}, existing={"src/ui/Button.tsx", "src/ui/Button.test.tsx"}
    )
    runner = FakeCommandRunner(_routes(token_defined=True))

    await verify_facts(_LOC_TRUE, "把提交按钮改为 primary-500", runner, reader, root="D:/proj")

    assert runner.cwds == ["D:/proj"] * 4


async def test_rg_cwd_is_none_for_default_root() -> None:
    """root 缺省（"." 或空）时不传 cwd，保持「从当前目录搜」的旧语义。"""
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE}, existing={"src/ui/Button.tsx"})
    runner = FakeCommandRunner(_routes(token_defined=True))

    await verify_facts(_LOC_TRUE, "把提交按钮改为 primary-500", runner, reader)

    assert set(runner.cwds) == {None}


async def test_token_pattern_uses_dash_e() -> None:
    """token 以 `--` 开头，必须经 -e 传入，否则 rg 会把它当选项（rg: unrecognized flag）。"""
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE}, existing={"src/ui/Button.tsx"})
    runner = FakeCommandRunner(_routes(token_defined=True))

    await verify_facts(_LOC_TRUE, "把提交按钮改为 primary-500", runner, reader)

    token_args = next(
        a for a in runner.calls if any(x.startswith("--route-key=tokdef:") for x in a)
    )
    assert token_args[token_args.index("-e") + 1] == "--color-primary-500"


async def test_all_true_case() -> None:
    reader = FakeFileReader(
        {"src/ui/Button.tsx": _FILE, "src/ui/Button.test.tsx": "it works"},
        existing={"src/ui/Button.tsx", "src/ui/Button.test.tsx"},
    )
    verdict = await _verify(_LOC_TRUE, reader, _routes(token_defined=True))
    assert len(verdict) == 7
    assert all(v == "pass" for v in verdict.values())


async def test_missing_token_and_test_fails() -> None:
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE}, existing={"src/ui/Button.tsx"})
    routes = _routes(token_defined=False)
    routes[("rg", "testid:src/ui/Button.tsx")] = ""  # 无 testid
    routes[("rg", "states:src/ui/Button.tsx")] = ""  # 无多状态
    verdict = await _verify(_LOC_TRUE, reader, routes)
    assert verdict["token_defined"] == "fail"
    assert verdict["test_file_exists"] == "fail"
    assert verdict["has_data_testid"] == "fail"
    assert verdict["has_state_styles"] == "fail"


async def test_no_unknown_verdict_and_evidence_present() -> None:
    reader = FakeFileReader({"src/ui/Button.tsx": _FILE}, existing={"src/ui/Button.tsx"})
    runner = FakeCommandRunner(_routes(token_defined=True))
    results = await verify_facts(_LOC_TRUE, "任意原句", runner, reader)
    assert all(r.evidence != "" and r.evidence != "未知" for r in results)
    assert {r.key for r in results} == {
        "target_file_exists",
        "symbol_in_file",
        "token_defined",
        "has_data_testid",
        "has_state_styles",
        "file_type_matches",
        "test_file_exists",
    }


async def test_backend_file_marks_style_facts_not_applicable() -> None:
    """非前端文件：token / testid / 状态样式三项不适用，其余四项照常判定。"""
    loc = CodeLocation(
        symbol_name="normalize_fit",
        path="src/app/score.py",
        definition_line=12,
        test_paths=["src/app/score_test.py"],
    )
    reader = FakeFileReader(
        {"src/app/score.py": "def normalize_fit(value):\n    return value"},
        existing={"src/app/score.py", "src/app/score_test.py"},
    )
    runner = FakeCommandRunner(
        {("rg", "symbol:src/app/score.py"): "src/app/score.py:12:def normalize_fit"}
    )

    results = await verify_facts(loc, "把打分归一化改一下", runner, reader)

    by_key = {r.key: r for r in results}
    frontend_keys: tuple[FactKey, ...] = (
        "target_file_exists",
        "symbol_in_file",
        "file_type_matches",
        "test_file_exists",
    )
    style_keys: tuple[FactKey, ...] = ("token_defined", "has_data_testid", "has_state_styles")
    for key in frontend_keys:
        assert by_key[key].applicable is True, key
    for key in style_keys:
        assert by_key[key].applicable is False, key
    assert is_evidence_complete(results) is True, "适用项全过即完备"
    assert all(r.evidence != "" for r in results)


async def test_frontend_file_keeps_all_facts_applicable() -> None:
    """前端文件保持改造前行为：七项全部适用。"""
    reader = FakeFileReader(
        {"src/ui/Button.tsx": _FILE},
        existing={"src/ui/Button.tsx", "src/ui/Button.test.tsx"},
    )
    runner = FakeCommandRunner(_routes(token_defined=True))

    results = await verify_facts(_LOC_TRUE, "把提交按钮改为 primary-500", runner, reader)

    assert all(r.applicable for r in results)


_JS_THEME_LOC = CodeLocation(
    symbol_name="BookListPage",
    path="src/pages/bookManage/BookListPage.tsx",
    definition_line=55,
    tokens=[],  # AntD 项目：目标文件没有 CSS 自定义属性
    token_hits=("src/styles/antdTheme.ts:10:    colorError: '#ff4d4f',",),
)
_JS_THEME_READER_FILES = {"src/pages/bookManage/BookListPage.tsx": _FILE}


async def test_token_defined_falls_back_to_js_theme() -> None:
    """无 CSS 变量时用 locate 阶段探到的 JS 主题键判定，避免 AntD 项目恒为假。"""
    reader = FakeFileReader(
        _JS_THEME_READER_FILES,
        existing={"src/pages/bookManage/BookListPage.tsx"},
    )
    runner = FakeCommandRunner(
        {
            ("rg", "symbol:src/pages/bookManage/BookListPage.tsx"): (
                "src/pages/bookManage/BookListPage.tsx:55:export default function BookListPage"
            )
        }
    )

    results = await verify_facts(_JS_THEME_LOC, "把新增图书按钮改为红色", runner, reader)

    token_fact = next(r for r in results if r.key == "token_defined")
    assert token_fact.passed is True
    assert token_fact.evidence.startswith("theme: ")
    assert "colorError" in token_fact.evidence
    # 目标文件无 CSS 变量时不得发起 css 搜索（零额外子进程）
    assert not any("tokdef:" in arg for call in runner.calls for arg in call)


async def test_token_defined_fails_without_css_or_theme_evidence() -> None:
    """既无 CSS 变量也无主题命中时仍判失败，不得无条件放行。"""
    loc = CodeLocation(
        symbol_name="BookListPage",
        path="src/pages/bookManage/BookListPage.tsx",
        definition_line=55,
        tokens=[],
        token_hits=(),
    )
    reader = FakeFileReader(
        _JS_THEME_READER_FILES,
        existing={"src/pages/bookManage/BookListPage.tsx"},
    )
    runner = FakeCommandRunner(
        {
            ("rg", "symbol:src/pages/bookManage/BookListPage.tsx"): (
                "src/pages/bookManage/BookListPage.tsx:55:export default function BookListPage"
            )
        }
    )

    results = await verify_facts(loc, "把新增图书按钮改为红色", runner, reader)

    token_fact = next(r for r in results if r.key == "token_defined")
    assert token_fact.passed is False
    assert token_fact.evidence == "未找到"


async def test_ui_library_project_marks_state_styles_not_applicable() -> None:
    """AntD 项目：状态样式由组件库提供，目标文件零命中 → 判不适用而非未通过。"""
    antd_file = "\n".join(
        [
            "import { Button } from 'antd';",
            "export default function BookListPage() {",
            '  return <Button type="primary">新增图书</Button>;',
            "}",
        ]
    )
    loc = CodeLocation(
        symbol_name="BookListPage",
        path="src/pages/BookListPage.tsx",
        definition_line=2,
    )
    reader = FakeFileReader({loc.path: antd_file}, existing={loc.path})
    runner = FakeCommandRunner(
        {("rg", f"symbol:{loc.path}"): (f"{loc.path}:2:export default function BookListPage")}
    )

    results = await verify_facts(loc, "把新增图书按钮改为红色", runner, reader)

    state_fact = next(r for r in results if r.key == "has_state_styles")
    assert state_fact.passed is False
    assert state_fact.applicable is False
    assert state_fact.evidence == "ui_lib=antd"


async def test_non_ui_library_file_keeps_state_styles_applicable() -> None:
    """未导入已知组件库时保持原判据：零命中即未通过且仍适用。"""
    loc = CodeLocation(
        symbol_name="SubmitButton",
        path="src/ui/Button.tsx",
        definition_line=1,
    )
    reader = FakeFileReader({loc.path: _FILE}, existing={loc.path})
    routes = _routes(token_defined=True)
    routes[("rg", f"states:{loc.path}")] = ""

    results = await verify_facts(
        loc, "把提交按钮改为 primary-500", FakeCommandRunner(routes), reader
    )

    state_fact = next(r for r in results if r.key == "has_state_styles")
    assert state_fact.passed is False
    assert state_fact.applicable is True


def test_is_evidence_complete_ignores_not_applicable_failures() -> None:
    facts = [
        FactResult("target_file_exists", True, "file=a.py"),
        FactResult("symbol_in_file", True, "a.py:1:x"),
        FactResult("token_defined", False, "未找到", applicable=False),
    ]

    assert is_evidence_complete(facts) is True
    assert is_evidence_complete([]) is False
    assert is_evidence_complete([FactResult("symbol_in_file", False, "")]) is False


def test_probe_complete_requires_judgement_when_unmeasured() -> None:
    """模型没给任何判定时不得判完备——这是静默降质的入口（2026-11-07）。"""
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=False,
            confidence=None,
            threshold=0.75,
            has_unknowns=False,
            judged=False,
        )
        is False
    )
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=False,
            confidence=None,
            threshold=0.75,
            has_unknowns=False,
            judged=True,
        )
        is True
    )


def test_probe_complete_requires_confidence_above_threshold() -> None:
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=True,
            confidence=0.8,
            threshold=0.75,
            has_unknowns=False,
            judged=True,
        )
        is True
    )
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=True,
            confidence=0.5,
            threshold=0.75,
            has_unknowns=False,
            judged=True,
        )
        is False
    )
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=True,
            confidence=None,
            threshold=0.75,
            has_unknowns=False,
            judged=True,
        )
        is False
    )


def test_probe_complete_rejects_unknowns_or_incomplete_evidence() -> None:
    assert (
        is_probe_complete(
            evidence_ok=False,
            measured=True,
            confidence=1.0,
            threshold=0.75,
            has_unknowns=False,
            judged=True,
        )
        is False
    )
    assert (
        is_probe_complete(
            evidence_ok=True,
            measured=True,
            confidence=1.0,
            threshold=0.75,
            has_unknowns=True,
            judged=True,
        )
        is False
    )
