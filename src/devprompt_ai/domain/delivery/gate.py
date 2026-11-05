"""交付证据门（2026-11-05）：三态判定，只控质量标记，不阻断交付。

天枢交付门禁的转译（`src/agent/deliver-task.ts:122` + `delivery-gate-v2.ts:90`）。
本项目交付的是**提示词**而非代码改动，因此门控对象从「能否 commit」换成
「能否标 C 档 / 能否标推荐」：

| 状态 | 含义 | 后果 |
|---|---|---|
| GREEN | 适用事实全过且断言有据 | 允许标 C 与推荐（仍受 MUST-27 双阈值约束） |
| YELLOW | 证据可用但不足以背书 | 保留原档位，不标推荐或附原因 |
| RED | 证据链断裂 | 不标 C、不标推荐，必须披露原因 |

**门禁不阻断交付**：与天枢真实行为一致（其 RED 也只披露不阻断），且符合 MUST-27
「不标记必须给具体原因，不得静默」——阻断会让用户拿不到任何东西。

纯函数、零 I/O：不读 session、不写日志、不调用 LLM。文案按 ``locale`` 从
``common/i18n.py`` 取（2026-11-06），默认 zh-CN。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from devprompt_ai.common.i18n import DEFAULT_LOCALE, Locale, tr
from devprompt_ai.domain.generate.claims import CLAIM_COVERAGE_MIN
from devprompt_ai.domain.models import FactResult

DeliveryStatus = Literal["GREEN", "YELLOW", "RED"]


@dataclass(frozen=True, slots=True)
class DeliveryInput:
    """判定输入（全部来自会话已有字段）。"""

    has_target: bool
    facts: Sequence[FactResult] = ()
    #: claims 覆盖率；None 表示本轮没有可核对的断言
    claim_coverage: float | None = None
    claims_undeclared: bool = False
    variant_count: int = 0
    #: 本轮请求的期望套数（U-7）；实际不足时 YELLOW 披露，None 表示不核对
    expected_variant_count: int | None = None
    #: C 档正文锚点校验（U-2）：明确无效的锚点数（文件不存在或行号越界）→ RED
    anchor_invalid_count: int = 0
    #: `decide_mark` 的结论；None 表示未打分（单套方案）
    recommend_marked: bool | None = None
    recommend_reason: str = ""


@dataclass(frozen=True, slots=True)
class DeliveryVerdict:
    """一次判定结果。``disclosure`` 非空时必须原样呈现给用户。

    ``tone`` 是**领域层给出的语义色阶**（ok / warn / error）：前端只按它选样式，
    不得自行把 status 映射成语义或出现任何阈值（MUST-08 / MUST-33）。
    """

    status: DeliveryStatus
    reasons: tuple[str, ...]
    can_mark_c: bool
    can_mark_recommend: bool
    disclosure: str
    tone: Literal["ok", "warn", "error"] = "ok"


def _join(items: Sequence[str], locale: Locale) -> str:
    """按语言拼列表：中文用顿号，英文用逗号。"""
    return tr("common.list_sep", locale).join(items)


def evaluate_delivery(data: DeliveryInput, locale: Locale = DEFAULT_LOCALE) -> DeliveryVerdict:
    """按 RED → YELLOW → GREEN 优先级判定，命中即返回。"""
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
            can_mark_c=False,
            can_mark_recommend=False,
            disclosure=tr(
                "gate.disclosure.red",
                locale,
                reasons=_join(red, locale),
            ),
            tone="error",
        )

    yellow: list[str] = []
    if data.claim_coverage is not None and data.claim_coverage < CLAIM_COVERAGE_MIN:
        yellow.append(
            tr(
                "gate.yellow.coverage",
                locale,
                coverage=f"{data.claim_coverage:.0%}",
                threshold=f"{CLAIM_COVERAGE_MIN:.0%}",
            )
        )
    if data.expected_variant_count is not None and data.variant_count < data.expected_variant_count:
        yellow.append(tr("gate.yellow.variant_short", locale, count=data.variant_count))
    if data.variant_count < 2:
        yellow.append(tr("gate.yellow.single_variant", locale))
    if data.recommend_marked is False:
        # 推荐理由由 decide_mark 生成（同一层已按语言输出），空则给兜底文案
        yellow.append(data.recommend_reason or tr("gate.yellow.no_recommend", locale))
    if yellow:
        return DeliveryVerdict(
            status="YELLOW",
            reasons=tuple(yellow),
            can_mark_c=True,
            can_mark_recommend=False,
            disclosure=tr(
                "gate.disclosure.yellow",
                locale,
                reasons=_join(yellow, locale),
            ),
            tone="warn",
        )

    return DeliveryVerdict(
        status="GREEN",
        reasons=(),
        can_mark_c=True,
        can_mark_recommend=data.variant_count >= 2,
        disclosure="",
        tone="ok",
    )
