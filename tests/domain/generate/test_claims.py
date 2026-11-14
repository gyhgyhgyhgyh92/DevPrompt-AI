"""断言级证据账本（domain/generate/claims）纯函数测试。

覆盖：全命中、部分命中、未声明（不惩罚）、事实未通过、路径分隔符归一；以及
2026-11-11 修正后的证据源——目标代码片段 / 设计令牌证据支撑的四类正向断言，
与 ``negates=test`` 的否定断言。
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


def test_absence_claim_covered_when_fact_failed() -> None:
    """如实报告「未找到某 token」：对应取证失败即算覆盖（2026-11-06 kind=absence）。

    为什么需要这个类型：此前 `passed=False` 一律记 uncovered——模型越诚实（明确说
    「没有这个 token」）反而越被扣分，覆盖率被否定性结论拖成 YELLOW。
    """
    claims = [
        Claim(kind="file", target="src/ui/button.tsx"),
        Claim(kind="absence", target="--color-primary-500", negates="token"),
    ]

    report = match_claims(claims, _facts(token_passed=False))

    assert report.covered == 2
    assert report.absent_ok == 1
    assert report.coverage == 1.0
    assert report.uncovered == ()


def test_absence_claim_uncovered_when_fact_passed() -> None:
    """说「没有」但取证实际找到了——这才是错误断言，必须记 uncovered。"""
    claims = [Claim(kind="absence", target="--color-x", negates="token")]

    report = match_claims(claims, _facts(token_passed=True))

    assert report.covered == 0
    assert report.absent_ok == 0
    assert report.uncovered == ("--color-x",)
    assert report.coverage == 0.0


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


# ---- 2026-11-11 账本修正：片段 / 令牌 / 路径证据支撑的断言 ----


_EVIDENCE_TEXT = (
    "src/pages/UserList.tsx\n"
    '233|  <Button type="primary" danger />\n'
    "src/styles/antdTheme.ts:8:  colorError: '#ff4d4f'"
)


def test_symbol_claim_covered_by_target_excerpt() -> None:
    """引用 JSX 组件（Button）：片段里出现即覆盖，不再要求 FactResult 证据命中。"""
    report = match_claims([Claim(kind="symbol", target="Button")], [], _EVIDENCE_TEXT)

    assert report.covered == 1
    assert report.coverage == 1.0


def test_file_claim_covered_by_token_evidence_path() -> None:
    """跨文件引用（antdTheme.ts）：令牌证据里含该路径即覆盖。"""
    report = match_claims(
        [Claim(kind="file", target="src/styles/antdTheme.ts")], [], _EVIDENCE_TEXT
    )

    assert report.covered == 1


def test_line_claim_covered_by_numbered_excerpt() -> None:
    """行号断言：片段出现 ``233|`` 且路径一致即覆盖。"""
    report = match_claims(
        [Claim(kind="line", target="src/pages/UserList.tsx:233")], [], _EVIDENCE_TEXT
    )

    assert report.covered == 1

    wrong_line = match_claims(
        [Claim(kind="line", target="src/pages/UserList.tsx:999")], [], _EVIDENCE_TEXT
    )
    assert wrong_line.covered == 0


def test_token_claim_covered_by_design_tokens() -> None:
    """令牌断言：设计令牌证据包含 colorError 即覆盖。"""
    report = match_claims([Claim(kind="token", target="colorError")], [], _EVIDENCE_TEXT)

    assert report.covered == 1


def test_absence_of_test_file_covered_by_failed_fact() -> None:
    """``absence negates=test``：测试文件不存在（fact 失败）才算如实覆盖。"""
    facts = [FactResult("test_file_exists", False, "未找到")]

    report = match_claims([Claim(kind="absence", target="未找到测试文件", negates="test")], facts)

    assert report.covered == 1
    assert report.absent_ok == 1
    assert report.coverage == 1.0
