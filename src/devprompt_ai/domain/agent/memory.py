"""跨轮继承契约（2026-11-04 多轮；纯数据 + 纯函数，零 I/O，MUST-06）。

多轮不再整体重置 ``session.data``，而是由本模块描述「上一轮有什么值得带走」：

- ``variants``   上一轮的三套方案正文（方案迭代轮直接在它上面改）；
- ``clarifications`` 上一轮已确认的问答（受 MUST-26 单轮 4 问约束，天然有界）；
- ``facts`` + ``facts_mtime_digest`` 取证结论及其代码快照指纹。

指纹来自符号表缓存键（``symbols.cache_key``，root + 全量 mtime 摘要），零新增采集。
代码改了指纹就变，继承的取证随即判为 stale，必须重跑 ripgrep——避免拿旧行号当证据。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast, get_args

from devprompt_ai.domain.generate.ports import VariantDraft
from devprompt_ai.domain.models import FactKey, FactResult

#: FactKey 的可接受集合（从 Literal 定义直接取出，避免白名单与类型两处漂移）
_FACT_KEYS: Final[frozenset[str]] = frozenset(get_args(FactKey))

#: 继承的方案套数上限：只带最近一轮（MUST-28 最多 3 套），再多的历史没有复用价值。
MAX_INHERITED_VARIANTS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class TurnMemory:
    """一轮结束时的可继承状态。"""

    sentence: str = ""
    facts: tuple[FactResult, ...] = ()
    facts_mtime_digest: str = ""
    variants: tuple[VariantDraft, ...] = ()
    clarifications: Mapping[str, str] = field(default_factory=dict)
    #: 上一轮定位到的目标符号（name/path/line）。复用取证时必需，否则会重新定位。
    target: Mapping[str, object] | None = None

    @property
    def has_evidence(self) -> bool:
        return bool(self.facts)

    def is_stale(self, current_digest: str) -> bool:
        """继承的取证是否已过期。

        任一侧指纹缺失都按过期处理（fail-safe）：宁可多跑一次 ripgrep，
        也不拿无法证实新鲜度的行号当证据。
        """
        if not self.facts:
            return False
        if not self.facts_mtime_digest or not current_digest:
            return True
        return self.facts_mtime_digest != current_digest

    def inherit_for_next_turn(self, sentence: str) -> TurnMemory:
        """派生下一轮的起点：方案与取证沿用，原句为空时沿用上一轮目标。

        ``clarifications``（2026-11-05）：**继承**已确认的问答。旧口径刻意不继承，
        代价是零基础用户每轮都要重答一遍「改哪个页面」——被反复追问是最快的信任流失。
        继承的答案只在**同一个目标**下成立：目标变了由 service 层作废并留痕
        （见 ``service._validate_inherited_clarifications``）。
        """
        return TurnMemory(
            sentence=sentence.strip() or self.sentence,
            facts=self.facts,
            facts_mtime_digest=self.facts_mtime_digest,
            variants=self.variants[:MAX_INHERITED_VARIANTS],
            clarifications=dict(self.clarifications),
            target=self.target,
        )

    def to_payload(self) -> dict[str, Any]:
        """序列化成可入 ``session.data`` 的 JSON 友好结构。"""
        return {
            "sentence": self.sentence,
            "facts": [
                {
                    "key": f.key,
                    "passed": f.passed,
                    "evidence": f.evidence,
                    "applicable": f.applicable,
                }
                for f in self.facts
            ],
            "facts_mtime_digest": self.facts_mtime_digest,
            "variants": [v.model_dump() for v in self.variants],
            "clarifications": dict(self.clarifications),
            "target": dict(self.target) if self.target is not None else None,
        }

    @classmethod
    def from_payload(cls, payload: object) -> TurnMemory:
        """从 ``session.data["turn_memory"]`` 还原；畸形数据按空记忆处理，不抛异常。

        旧会话没有这个键（改造前写入的 payload），空记忆等价于「没有可继承内容」。
        """
        if not isinstance(payload, dict):
            return cls()
        raw_facts = payload.get("facts")
        facts: list[FactResult] = []
        if isinstance(raw_facts, list):
            for item in raw_facts:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                passed = item.get("passed")
                if not isinstance(key, str) or not isinstance(passed, bool):
                    continue
                if key not in _FACT_KEYS:
                    continue  # 越界键直接丢弃：七项之外的事实不参与对账
                facts.append(
                    FactResult(
                        key=cast(FactKey, key),
                        passed=passed,
                        evidence=str(item.get("evidence", "")),
                        # 旧 payload 无此字段：按适用处理，与改造前行为一致
                        applicable=bool(item.get("applicable", True)),
                    )
                )
        raw_variants = payload.get("variants")
        variants: list[VariantDraft] = []
        if isinstance(raw_variants, list):
            for item in raw_variants:
                if not isinstance(item, dict):
                    continue
                try:
                    variants.append(VariantDraft(**item))
                except (TypeError, ValueError):
                    continue
        raw_clar = payload.get("clarifications")
        clarifications: dict[str, str] = {}
        if isinstance(raw_clar, dict):
            clarifications = {str(k): str(v) for k, v in raw_clar.items()}
        raw_target = payload.get("target")
        target: dict[str, object] | None = None
        if isinstance(raw_target, dict) and "name" in raw_target and "path" in raw_target:
            target = dict(raw_target)
        return cls(
            sentence=str(payload.get("sentence", "")),
            facts=tuple(facts),
            facts_mtime_digest=str(payload.get("facts_mtime_digest", "")),
            variants=tuple(variants[:MAX_INHERITED_VARIANTS]),
            clarifications=clarifications,
            target=target,
        )
