"""代码工程包：仓库上下文领域，行为与领域化改造前完全一致（硬验收：零回归）。"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.agent.action import AgentAction
from devprompt_ai.domain.domains.ports import DomainPack

#: 与 generate/claims.py 的 _KIND_FACT 保持一致（test 仅用于 absence.negates）。
CODE_CLAIM_KINDS: Final[frozenset[str]] = frozenset({"file", "symbol", "line", "token", "test"})


def code_pack() -> DomainPack:
    return DomainPack(
        id="code",
        needs_repo=True,
        allowed_actions=frozenset(AgentAction),
        claim_kinds=CODE_CLAIM_KINDS,
        keywords=(
            "代码",
            "函数",
            "接口",
            "组件",
            "页面",
            "样式",
            "前端",
            "后端",
            "重构",
            "报错",
            "报异常",
            "编译",
            "部署",
            "测试用例",
            "数据库",
            "api",
            "bug",
            "refactor",
            "deploy",
        ),
        name_key="domain.code.name",
        directives_key="",
        sections_key="template.body_semantics",
    )
