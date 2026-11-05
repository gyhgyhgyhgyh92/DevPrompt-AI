"""断言级证据账本（domain/generate/claims）纯函数测试。

覆盖：全命中、部分命中、未声明（不惩罚）、事实未通过、路径分隔符归一。
"""

from devprompt_ai.domain.generate.claims import CLAIM_COVERAGE_MIN, ClaimReport, match_claims
from devprompt_ai.domain.generate.ports import Claim
from devprompt_ai.domain.models import FactResult


def _facts(*, token_passed: bool = True) -> list[FactResult]:
    return [
        FactResult("target_file_exists", True, "file=src/ui/button.tsx"),
        FactResult("symbol_in_file", True, "src/ui/button.tsx:12:export function SubmitButton"),
        FactResult(
            "token_defined",
            token_passed,
            "src/tokens.css:1:--color-x" if token_passed else "未找到",
        ),
    ]


def test_all_claims_covered() -> None:
    claims = [
        Claim(kind="file", target="src/ui/button.tsx"),
        Claim(kind="symbol", target="SubmitButton"),
        Claim(kind="line", target="src/ui/button.tsx:12"),
        Claim(kind="token", target="--color-x"),
    ]

    report = match_claims(claims, _facts())

    assert isinstance(report, ClaimReport)
    assert report.total == 4
    assert report.covered == 4
    assert report.coverage == 1.0
    assert report.uncovered == ()


def test_half_covered_lists_uncovered() -> None:
    claims = [
        Claim(kind="file", target="src/ui/button.tsx"),
        Claim(kind="file", target="src/ui/missing.tsx"),
    ]

    report = match_claims(claims, _facts())

    assert report.coverage == 0.5
    assert report.uncovered == ("src/ui/missing.tsx",)
    assert report.coverage < CLAIM_COVERAGE_MIN


def test_empty_claims_is_marked_undeclared() -> None:
    """空声明不再视为全覆盖（2026-11-05）：coverage 记 0 并显式标记。

    是否据此降档由调用方决定（service 的 claim_strict 灰度），领域层只如实报告——
    「不声明」与「声明了但没取证」必须能区分开。
    """
    report = match_claims([], _facts())

    assert report.total == 0
    assert report.coverage == 0.0
    assert report.undeclared is True
    assert report.render() == "未声明引用，证据链无法核对"


def test_failed_fact_counts_as_uncovered() -> None:
    claims = [Claim(kind="token", target="--color-x")]

    report = match_claims(claims, _facts(token_passed=False))

    assert report.covered == 0
    assert report.uncovered == ("--color-x",)


def test_backslash_path_is_normalized() -> None:
    claims = [Claim(kind="file", target=r"src\ui\button.tsx")]

    report = match_claims(claims, _facts())

    assert report.coverage == 1.0


def test_render_reports_gap() -> None:
    claims = [
        Claim(kind="file", target="src/ui/button.tsx"),
        Claim(kind="file", target="nope.tsx"),
    ]

    assert match_claims(claims, _facts()).render() == "已核对断言 1/2，1 处未取证"
