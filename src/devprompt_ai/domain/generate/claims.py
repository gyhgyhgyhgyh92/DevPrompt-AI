"""断言级证据账本（2026-11-04，纯函数零 I/O，MUST-06）。

方案的「完整路径 + 行号 + token 出处」承诺需要机器校验，但生成后校验若只查标题/正文
非空——证据链在「七项事实通过」与「方案正文」之间就是断的。这里补上对账环节：

模型在生成同一次调用里逐条声明引用（``VariantDraft.claims``），本模块把每条断言映射到
负责核对的 ``FactResult``，覆盖不足时由调用方降档——不重新生成，只标注与留痕。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.ports import Claim
from devprompt_ai.domain.models import FactResult

#: 可交付的最低断言覆盖率。低于它说明正文引用大面积无取证支撑（MUST-08：唯一判定位置）。
CLAIM_COVERAGE_MIN: Final[float] = 0.8

#: claim.kind → 负责核对该断言的事实键。
#: ``test`` 只出现在 ``absence.negates`` 里（2026-11-11）：核测试文件是否存在。
_KIND_FACT: Final[dict[str, str]] = {
    "file": "target_file_exists",
    "symbol": "symbol_in_file",
    "line": "symbol_in_file",
    "token": "token_defined",
    "test": "test_file_exists",
}


@dataclass(frozen=True, slots=True)
class ClaimReport:
    """一次对账结果。

    ``undeclared=True``（2026-11-05）：模型一条引用都没声明。此前 coverage 记 1.0，
    等于「不声明 = 完全覆盖」，是断言对账唯一可被绕过的口子；现在记 0 并显式标记。
    """

    total: int
    covered: int
    uncovered: tuple[str, ...]
    coverage: float
    undeclared: bool = False
    #: 其中「如实报告某引用不存在」且取证实为失败（kind=absence）的条数（2026-11-06）。
    absent_ok: int = 0

    def render(self, locale: Locale = DEFAULT_LOCALE) -> str:
        """快照用的一句摘要（前端直接展示，不含判定）。"""
        if self.undeclared:
            return tr("claims.render.undeclared", locale)
        if self.total == 0:
            return ""
        missing = len(self.uncovered)
        text = tr(
            "claims.render.summary",
            locale,
            covered=self.covered,
            total=self.total,
            missing=missing,
        )
        if self.absent_ok:
            text += tr("claims.render.absent", locale, count=self.absent_ok)
        return text


def _normalize(text: str) -> str:
    return text.replace("\\", "/").strip().lower()


def _line_hit(target: str, haystack: str) -> bool:
    """line 断言的证据形态是片段里的「行号|内容」标记，而非「路径:行号」整串。

    2026-11-11：``target=src/pages/X.tsx:233`` 只要片段出现 ``233|``（且路径也在
    证据里）即视为覆盖，否则行号断言在四段式正文里几乎永远核不上。
    """
    path, sep, line = target.rpartition(":")
    number = line.strip()
    if not sep or not number.isdigit():
        return False
    if f"{number}|" not in haystack:
        return False
    path_needle = _normalize(path)
    return not path_needle or path_needle in haystack


def match_claims(
    claims: Sequence[Claim], facts: Sequence[FactResult], evidence_text: str = ""
) -> ClaimReport:
    """逐条核对断言是否被取证支撑。

    ``evidence_text``（2026-11-11）承载「目标代码片段 + 设计令牌证据 + 目标文件路径」，
    是 symbol / file / line / token 四类断言的**首选**证据源：命中即算覆盖。此前只核
    ``FactResult.evidence``，导致引用 JSX 组件、跨文件路径、行号、AntD 类 token 的断言
    恒判未覆盖（账本失真）。

    匹配不到时回退旧判据：对应事实 ``passed`` 且该事实证据文本含 ``target``。
    匹配一律大小写不敏感，路径反斜杠归一为正斜杠。

    空 claims 按「未声明」处理，coverage 记 0，不视为完全覆盖。
    """
    if not claims:
        return ClaimReport(total=0, covered=0, uncovered=(), coverage=0.0, undeclared=True)

    index: dict[str, FactResult] = {f.key: f for f in facts}
    haystack = _normalize(evidence_text)
    uncovered: list[str] = []
    covered = 0
    absent_ok = 0
    for claim in claims:
        if claim.kind == "absence":
            # 「未找到 X」这类**如实的否定结论**（2026-11-06）：判据与正向声明相反——
            # 该类别取证**失败**才算覆盖（东西确实不存在）；取证通过说明东西其实存在，
            # 这条否定声明本身就是错的，记 uncovered。
            # 上限：失败时证据文本恒为「未找到」、不含 target，故无法核到具体名字。
            fact_key = _KIND_FACT.get(claim.negates or "")
            fact = index.get(fact_key) if fact_key is not None else None
            if fact is not None and not fact.passed:
                absent_ok += 1
                covered += 1
            else:
                uncovered.append(claim.target)
            continue
        needle = _normalize(claim.target)
        if (needle and needle in haystack) or (
            claim.kind == "line" and _line_hit(claim.target, haystack)
        ):
            covered += 1
            continue
        fact_key = _KIND_FACT.get(claim.kind)
        fact = index.get(fact_key) if fact_key is not None else None
        if fact is None or not fact.passed:
            uncovered.append(claim.target)
            continue
        if needle and needle in _normalize(fact.evidence):
            covered += 1
        else:
            uncovered.append(claim.target)

    total = len(claims)
    return ClaimReport(
        total=total,
        covered=covered,
        uncovered=tuple(uncovered),
        coverage=covered / total,
        absent_ok=absent_ok,
    )
