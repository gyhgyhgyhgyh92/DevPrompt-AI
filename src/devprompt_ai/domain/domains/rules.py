"""确定性领域路由（纯函数，零 LLM 成本，MUST-06 domain 无 I/O）。

两级路由的第一级：注册包词表按注册顺序匹配，命中即返回——覆盖「帮我写周报」
这类含明显领域词的输入。未命中交给决策层 LLM 分类（decision/domains.py）。
"""

from __future__ import annotations

from devprompt_ai.domain.domains.ports import DomainId
from devprompt_ai.domain.domains.registry import all_packs

#: keyword 命中的固定置信度：词表是确定性证据，高于 LLM 自评的通常水平。
KEYWORD_CONFIDENCE: float = 0.9


def match_by_keyword(sentence: str) -> tuple[DomainId, float] | None:
    """按注册顺序匹配词表；命中返回 (领域, 置信度)，全未命中返回 None。

    词表按注册顺序（code → work → life → creative）先到先得；英文词按
    casefold 匹配（slogan/SLOGAN 同判），中文不受影响。
    """
    lowered = sentence.casefold()
    for pack in all_packs():
        for kw in pack.keywords:
            if kw.casefold() in lowered:
                return pack.id, KEYWORD_CONFIDENCE
    return None
