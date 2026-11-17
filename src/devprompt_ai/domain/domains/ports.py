"""领域包契约与路由结论（纯数据，零 I/O，MUST-06）。

领域包 = 一个场景领域的最小静态描述：模板分段语义与领域指令走 i18n 键
（``common/i18n.py``），动作与断言白名单用 frozenset 声明。包本体不执行任何逻辑——
路由判定在 ``decision/domains.py``（LLM）与关键词规则，动作过滤在
``service.run_agent_loop``，断言核验在 ``domain/delivery/gate.py``（MUST-08）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, Field

from devprompt_ai.domain.agent.action import AgentAction

#: 预置领域包标识。新增领域包：加成员 + packs/ 新包文件 + registry 注册 + i18n 文案。
DomainId: TypeAlias = Literal[
    "code",
    "work",
    "life",
    "creative",
    "visual",
    "learning",
    "data",
    "marketing",
    "translation",
    "legal",
    "medical",
    "finance",
    "game",
    "av",
    "operations",
]

#: 全部合法领域 id（路由白名单与前端契约校验用，顺序即注册顺序/UI 展示顺序）。
#: visual 排在 marketing 之前：文生图/即梦等强特征词须先于「海报」等营销词命中。
KNOWN_DOMAIN_IDS: Final[tuple[str, ...]] = (
    "code",
    "work",
    "life",
    "creative",
    "visual",
    "learning",
    "data",
    "marketing",
    "translation",
    "legal",
    "medical",
    "finance",
    "game",
    "av",
    "operations",
)


@dataclass(frozen=True, slots=True)
class DomainPack:
    """一个场景领域的静态描述。纯数据：判定逻辑一律在消费方。"""

    id: DomainId
    #: True=依赖仓库上下文（检索/取证/锚点），空 project_root 拒绝（升级前行为）
    needs_repo: bool
    #: 本领域允许的 Agent 动作白名单；通用包剔除 RETRIEVE/PROBE/DELEGATE
    allowed_actions: frozenset[AgentAction]
    #: 本包合法断言 kinds（注入模板 claims_rules）；空集=无仓库证据断言，交付门走结构化校验
    claim_kinds: frozenset[str]
    #: 确定性路由词表（命中任一即判入本领域，零 LLM 成本；匹配逻辑在路由层）
    keywords: tuple[str, ...]
    #: i18n 键：领域名（domain.<id>.name）
    name_key: str
    #: i18n 键：领域指令（术语规范+约束补全+交付标准）；空串=无额外指令块
    #: （code 域复用既有模板语义，零回归）
    directives_key: str
    #: i18n 键：四段式分段语义（code 复用 template.body_semantics）
    sections_key: str


class DomainVerdict(BaseModel):
    """路由结论：值与质量标记成对返回（MUST-11d），随 session.data 与 trace 落库。"""

    domain: DomainId
    #: 结论来源：override=用户指定，project=带项目路径强制 code，keyword=词表命中，
    #: llm=决策层分类，fallback=全部未定走兜底包
    source: Literal["override", "project", "keyword", "llm", "fallback"]
    confidence: float = Field(ge=0.0, le=1.0)
