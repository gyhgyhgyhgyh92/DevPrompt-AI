"""F-104 七项事实测试：每项含真/假分支，证据非「未知」。"""

from fakes import FakeCommandRunner, FakeFileReader

from devprompt_ai.domain.models import CodeLocation, FactKey
from devprompt_ai.domain.retrieval.facts import verify_facts

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
