"""结构化 Query 改写（2026-11-19）：多轮指代/省略的目标变化检测。

纯规则、零 I/O、零 LLM 调用——只做「目标是否变了」的判定与检索词归一。
借鉴 LlamaIndex 的结构化 rewrite 形状（target/intent/entities/negation），
但不引入模型调用：项目已有上下文继承，规则级足够驱动重检索。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from devprompt_ai.common.text import tokenize_sentence

#: 代码标识符形态：驼峰 / 下划线 / 点号 / 连字符连接的符号名（排除纯中文与颜色值）。
_IDENTIFIER_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:[_\.][A-Za-z0-9]+)+\b|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b"
)

#: 指代/省略词：这些词单独出现时视为「沿用上一轮目标」。
_ANAPHORA: frozenset[str] = frozenset(
    {"这个", "那个", "它", "其", "此", "这", "那", "按钮", "上面", "上述", "继续", "再", "还"}
)
#: 意图关键词 → intent 标签。
_INTENT_WORDS: tuple[tuple[str, str], ...] = (
    ("改成", "modify"),
    ("改为", "modify"),
    ("换成", "modify"),
    ("不要", "negate"),
    ("去掉", "remove"),
    ("删除", "remove"),
    ("新增", "add"),
    ("添加", "add"),
    ("为什么", "diagnose"),
    ("排查", "diagnose"),
)


class QueryRewriteOutput(BaseModel):
    """LLM 改写的结构化输出（只定义形状；规则层与 LLM 层共用语义）。"""

    target: str = ""
    intent: str = "modify"
    entities: list[str] = Field(default_factory=list)
    negation: list[str] = Field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class RewrittenQuery:
    target: str
    intent: str
    entities: tuple[str, ...]
    negation: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "intent": self.intent,
            "entities": list(self.entities),
            "negation": list(self.negation),
            "confidence": self.confidence,
        }


def rewrite_query(sentence: str, previous_target: str = "") -> RewrittenQuery:
    """结构化改写：本轮有独立目标则 takeover，否则沿用上一轮 target。"""
    text = (sentence or "").strip()
    tokens = tuple(tokenize_sentence(text))
    intent = "modify"
    for word, label in _INTENT_WORDS:
        if word in text:
            intent = label
            break
    negation = tuple(word for word in ("不要", "去掉", "删除", "不") if word in text)

    # 独立目标：只认代码标识符形态（驼峰 / 下划线 / 点号）；含连字符的颜色值
    # （primary-600）与中文描述不算目标，避免样式微调被误判为换目标。
    symbolic = tuple(_IDENTIFIER_RE.findall(text))
    anaphora_only = bool(text) and all(word in _ANAPHORA for word in tokens) and not symbolic
    if symbolic and not anaphora_only:
        target = symbolic[0]
        confidence = 0.9
    elif anaphora_only and previous_target:
        target = previous_target
        confidence = 0.6
    elif previous_target:
        target = previous_target
        confidence = 0.3
    else:
        target = text[:60]
        confidence = 0.5
    return RewrittenQuery(
        target=target, intent=intent, entities=tokens[:8], negation=negation, confidence=confidence
    )


def target_changed(rewritten: RewrittenQuery, previous_target: str) -> bool:
    """改写后的目标与上一轮不同 → 事实复用短路必须放行重检索。"""
    if not previous_target:
        return False
    if rewritten.confidence < 0.6:
        return False
    return rewritten.target.strip().lower() != previous_target.strip().lower()
