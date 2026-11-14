"""交付证据门（2026-11-05）：三态判定，只控质量披露，不阻断交付。

天枢交付门禁的转译（`src/agent/deliver-task.ts:122` + `delivery-gate-v2.ts:90`）。
2026-11-11 单套输出后，门控对象收敛为「证据是否足以背书本轮方案」：

| 状态 | 含义 | 后果 |
|---|---|---|
| GREEN | 适用事实全过且断言有据 | 正常交付，无披露 |
| YELLOW | 证据可用但不足以背书 | 照常交付并披露缺口 |
| RED | 证据链断裂 | 照常交付并披露原因 |

**门禁不阻断交付**：与天枢真实行为一致（其 RED 也只披露不阻断），且符合 MUST-27
「不标记必须给具体原因，不得静默」——阻断会让用户拿不到任何东西。

纯函数、零 I/O：不读 session、不写日志、不调用 LLM。文案按 ``locale`` 从
``common/i18n.py`` 取（2026-11-06），默认 zh-CN。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.delivery.attribution import Attribution, GateColor, evaluate_attribution
from devprompt_ai.domain.generate.claims import CLAIM_COVERAGE_MIN
from devprompt_ai.domain.models import FactResult

if TYPE_CHECKING:
    from devprompt_ai.domain.delivery.structural import StructuralCheck

DeliveryStatus = Literal["GREEN", "YELLOW", "RED"]


@dataclass(frozen=True, slots=True)
class DeliveryInput:
    """判定输入（全部来自会话已有字段）。"""

    has_target: bool
    facts: Sequence[FactResult] = ()
    #: claims 覆盖率；None 表示本轮没有可核对的断言
    claim_coverage: float | None = None
    claims_undeclared: bool = False
    #: 正文锚点校验（U-2）：明确无效的锚点数（文件不存在或行号越界）→ RED
    anchor_invalid_count: int = 0
    #: 改动归属（E11）：None 表示无影响半径数据（未开 repo 图），不参与判定
    attribution: Attribution | None = None
    #: 通用域结构化校验结果（2026-11-14 领域包）：非 None 时走结构化分支，
    #: 忽略检索/取证/锚点/claims（通用域没有这些证据源）
    structural: StructuralCheck | None = None


@dataclass(frozen=True, slots=True)
class DeliveryVerdict:
    """一次判定结果。``disclosure`` 非空时必须原样呈现给用户。

    ``tone`` 是**领域层给出的语义色阶**（ok / warn / error）：前端只按它选样式，
    不得自行把 status 映射成语义或出现任何阈值（MUST-08 / MUST-33）。
    """

    status: DeliveryStatus
    reasons: tuple[str, ...]
    disclosure: str
    tone: Literal["ok", "warn", "error"] = "ok"


def _join(items: Sequence[str], locale: Locale) -> str:
    """按语言拼列表：中文用顿号，英文用逗号。"""
    return tr("common.list_sep", locale).join(items)


def _evaluate_structural(data: DeliveryInput, locale: Locale) -> DeliveryVerdict:
    """通用域分支（MUST-08：结构化判定在 structural.py，这里只拼门禁结论）。"""
    check = data.structural
    assert check is not None  # 分支条件已保证（evaluate_delivery 入口分流）
    red: list[str] = []
    if not check.body_sections_ok:
        red.append(tr("gate.red.structural_sections", locale))
    if not check.deliverables_declared:
        red.append(tr("gate.red.structural_deliverables", locale))
    if check.placeholder_count:
        red.append(tr("gate.red.structural_placeholder", locale, count=check.placeholder_count))
    if red:
        return DeliveryVerdict(
            status="RED",
            reasons=tuple(red),
            disclosure=tr("gate.disclosure.red", locale, reasons=_join(red, locale)),
            tone="error",
        )
    return DeliveryVerdict(status="GREEN", reasons=(), disclosure="", tone="ok")


def evaluate_delivery(data: DeliveryInput, locale: Locale = DEFAULT_LOCALE) -> DeliveryVerdict:
    """按 RED → YELLOW → GREEN 优先级判定，命中即返回。

    ``structural`` 非 None（通用域）时改核结构完整性：无仓库证据可查，
    事实/锚点/claims 均不适用。
    """
    if data.structural is not None:
        return _evaluate_structural(data, locale)
    applicable = [fact for fact in data.facts if fact.applicable]

    red: list[str] = []
    if not data.has_target:
        red.append(tr("gate.red.no_target", locale))
    elif applicable and not any(fact.passed for fact in applicable):
        red.append(tr("gate.red.facts_failed", locale))
    if data.claims_undeclared:
        red.append(tr("gate.red.claims_undeclared", locale))
    if data.anchor_invalid_count:
        red.append(tr("gate.red.anchor_invalid", locale, count=data.anchor_invalid_count))
    if red:
        return DeliveryVerdict(
            status="RED",
            reasons=tuple(red),
            disclosure=tr(
                "gate.disclosure.red",
                locale,
                reasons=_join(red, locale),
            ),
            tone="error",
        )

    yellow: list[str] = []
    if data.attribution is not None and (
        evaluate_attribution(data.attribution) is not GateColor.GREEN
    ):
        yellow.append(
            tr(
                "gate.yellow.impact_uncovered",
                locale,
                count=len(data.attribution.uncovered_impact),
            )
        )
    if data.claim_coverage is not None and data.claim_coverage < CLAIM_COVERAGE_MIN:
        yellow.append(
            tr(
                "gate.yellow.coverage",
                locale,
                coverage=f"{data.claim_coverage:.0%}",
                threshold=f"{CLAIM_COVERAGE_MIN:.0%}",
            )
        )
    if yellow:
        return DeliveryVerdict(
            status="YELLOW",
            reasons=tuple(yellow),
            disclosure=tr(
                "gate.disclosure.yellow",
                locale,
                reasons=_join(yellow, locale),
            ),
            tone="warn",
        )

    return DeliveryVerdict(status="GREEN", reasons=(), disclosure="", tone="ok")
