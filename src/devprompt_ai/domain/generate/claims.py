"""断言级证据账本（2026-11-04，纯函数零 I/O，MUST-06）。

C 档承诺「完整路径 + 行号 + token 出处」（MUST-28），但此前的生成后校验只查标题/正文
非空——证据链在「七项事实通过」与「方案正文」之间是断的。这里补上对账环节：

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

#: C 档可交付的最低断言覆盖率。低于它说明正文引用大面积无取证支撑（MUST-08：唯一判定位置）。
CLAIM_COVERAGE_MIN: Final[float] = 0.8

#: claim.kind → 负责核对该断言的事实键
_KIND_FACT: Final[dict[str, str]] = {
    "file": "target_file_exists",
    "symbol": "symbol_in_file",
    "line": "symbol_in_file",
    "token": "token_defined",
}


@dataclass(frozen=True, slots=True)
class ClaimReport:
    """一次对账结果。

    ``undeclared=True``（2026-11-05）：模型一条引用都没声明。此前 coverage 记 1.0，
    等于「不声明 = 完全覆盖」，是 C 档对账唯一可被绕过的口子；现在记 0 并显式标记。
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


def match_claims(claims: Sequence[Claim], facts: Sequence[FactResult]) -> ClaimReport:
    """逐条核对断言是否被取证支撑。

    判据：对应事实 ``passed`` 且 ``target`` 出现在该事实的证据文本里（大小写不敏感，
    路径正斜杠归一）。空 claims 按「未声明」处理，coverage 记 1.0，不惩罚旧输出。
    """
    if not claims:
        return ClaimReport(total=0, covered=0, uncovered=(), coverage=0.0, undeclared=True)

    index: dict[str, FactResult] = {f.key: f for f in facts}
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
        fact_key = _KIND_FACT.get(claim.kind)
        fact = index.get(fact_key) if fact_key is not None else None
        if fact is None or not fact.passed:
            uncovered.append(claim.target)
            continue
        needle = _normalize(claim.target)
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
