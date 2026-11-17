"""领域分类的 LLM 实现（两级路由的第二级；模式对齐 decision/fallback.py）。

MUST-12：决策层单一 LLM 实现——本文件与 ``fallback.py`` 同构，都是
``chat_structured`` 单次结构化调用。分类只发生在确定性词表未命中之后，
任何失败（超时/解析/非法领域）都回退兜底包并降置信度，不阻塞主链。
"""

from __future__ import annotations

import logging
from typing import cast

from pydantic import BaseModel, Field

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.domains.ports import KNOWN_DOMAIN_IDS, DomainId, DomainVerdict
from devprompt_ai.harness.llm import chat_structured
from devprompt_ai.observability.logging import emit_warning

logger = logging.getLogger("devprompt.decision")

#: 兜底包：全手段未定时的落点。选 work 而非 code——通用指令文本比仓库检索更安全。
FALLBACK_DOMAIN = "work"
#: fallback 的置信度语义为「未判定」（MUST-11d 质量标记），消费方不得当实测。
FALLBACK_CONFIDENCE = 0.0
#: LLM 自评置信度低于该值视为「模型自己不确定」——按 MUST-11d 不得当实测判定，
#: 回退兜底包而非采纳低置信结论。
LOW_CONFIDENCE_FALLBACK = 0.5

_DOMAIN_SYSTEM = (
    "你是场景领域分类器。把用户输入分类到唯一领域："
    "code=代码工程（写代码/改代码/调试/部署/技术方案）；"
    "work=工作事务（周报/汇报/总结/文档/邮件/方案/计划）；"
    "life=生活事务（行程/采购/健身/饮食/搬家/日程/装修）；"
    "creative=创意创作（故事/小说/命名/口号/脑暴）；"
    "learning=学习教育（课程/教案/复习/论文/考试/培训）；"
    "data=数据分析（数据清洗/统计/可视化/指标/报表解读）；"
    "marketing=文案营销（营销文案/投放/社媒内容/增长策划）；"
    "translation=翻译本地化（多语言翻译/本地化改写）；"
    "legal=法律合同（合同/协议/合规/法律文书）；"
    "medical=医疗健康（症状梳理/就医准备/康复记录，非诊断）；"
    "finance=金融财务（财报/税务/报销/预算核算/投资分析）；"
    "game=游戏设计（玩法/关卡/数值/剧情策划）；"
    "visual=视觉生成（文生图/图生图/文生视频的提示词优化，Midjourney/即梦/Sora/可灵等工具）；"
    "av=音视频脚本（视频脚本/分镜/口播稿/播客）；"
    "operations=运营策划（活动策划/社群/用户增长/内容排期）。"
    "只输出 JSON，不要解释。"
)

_DOMAIN_USER = (
    "输入：{sentence}\n"
    '输出 JSON：{{"domain": "code|work|life|creative|learning|data|marketing|translation|'
    'legal|medical|finance|game|visual|av|operations", "confidence": 0.0到1.0}}'
)

#: 分类只看一句话的领域指向，超长输入截断即可（分类不需要全文语义）。
_SENTENCE_LIMIT = 2000


class DomainClassifyOutput(BaseModel):
    """LLM 分类输出契约（chat_structured 的 schema 注入目标）。"""

    domain: str
    confidence: float = Field(ge=0.0, le=1.0)


class DomainClassifier:
    """决策层的领域分类器：确定性路由未命中时的一次 LLM 调用。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def classify(self, sentence: str) -> DomainVerdict:
        fallback = DomainVerdict(
            domain=cast(DomainId, FALLBACK_DOMAIN),
            source="fallback",
            confidence=FALLBACK_CONFIDENCE,
        )
        try:
            out = await chat_structured(
                self._cfg,
                DomainClassifyOutput,
                _DOMAIN_SYSTEM,
                _DOMAIN_USER.format(sentence=sentence[:_SENTENCE_LIMIT]),
                purpose="decide",
            )
        except Exception as exc:  # noqa: BLE001 - 分类失败不阻塞主链，回退兜底包
            logger.info("domain.classify_failed", extra={"what": type(exc).__name__})
            emit_warning("domain.classify_failed", what=type(exc).__name__)
            return fallback
        if out.domain not in KNOWN_DOMAIN_IDS:
            logger.info("domain.classify_invalid", extra={"what": out.domain})
            emit_warning("domain.classify_invalid", what=out.domain)
            return fallback
        if out.confidence < LOW_CONFIDENCE_FALLBACK:
            logger.info(
                "domain.classify_low_confidence",
                extra={"what": out.domain, "confidence": out.confidence},
            )
            emit_warning("domain.classify_low_confidence", what=out.domain)
            return fallback
        return DomainVerdict(
            domain=out.domain,  # type: ignore[arg-type]  # 上一行已收窄到 KNOWN_DOMAIN_IDS
            source="llm",
            confidence=out.confidence,
        )
