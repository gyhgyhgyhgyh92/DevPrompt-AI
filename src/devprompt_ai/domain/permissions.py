"""权限判定（D1–D5）：先否决、再豁免、最后才看审批模式。

铁律：**deny 绝对优先，BYPASS 也不能绕过**——跳过审批不等于跳过安全底线。
「总是允许」四层：会话命令前缀 / 永久白名单 / 文件级 / 路径子树。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final


class ApprovalMode(str, Enum):
    MANUAL = "manual"
    AUTO_SAFE = "auto-safe"
    BYPASS = "bypass"


class Risk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: 绝对拒绝：即便 BYPASS 也不放行。
DENY_PATTERNS: Final[tuple[str, ...]] = (
    "rm -rf /",
    "mkfs",
    "sudo ",
    "curl | sh",
    "curl|sh",
    "chmod -R 777 /",
    ":(){",
)

#: 恒定需要人工确认的工具（白名单也不能豁免）。
UNCONDITIONAL_TOOLS: Final[frozenset[str]] = frozenset(
    {"js_eval", "browser_adopt", "request_path_access"}
)


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    tool: str
    risk: Risk = Risk.LOW
    command: str = ""
    path: str = ""


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    needs_approval: bool
    reason: str


@dataclass
class PermissionPolicy:
    mode: ApprovalMode = ApprovalMode.MANUAL
    allowlist: set[str] = field(default_factory=set)
    bash_prefixes: set[str] = field(default_factory=set)
    file_approvals: set[str] = field(default_factory=set)
    path_grants: set[str] = field(default_factory=set)

    def is_denied(self, request: PermissionRequest) -> bool:
        haystack = f"{request.command} {request.path}".lower()
        return any(pattern in haystack for pattern in DENY_PATTERNS)

    def authorize(self, request: PermissionRequest) -> PermissionDecision:
        if self.is_denied(request):
            return PermissionDecision(False, False, "denied-pattern")

        if request.tool in UNCONDITIONAL_TOOLS and self.mode is not ApprovalMode.BYPASS:
            return PermissionDecision(False, True, "unconditional-tool")

        if self.mode is ApprovalMode.BYPASS:
            return PermissionDecision(True, False, "bypass")

        if request.tool in self.allowlist:
            return PermissionDecision(True, False, "allowlist")

        if request.command and any(
            request.command.startswith(prefix) for prefix in self.bash_prefixes
        ):
            return PermissionDecision(True, False, "bash-prefix")

        if request.path and (
            request.path in self.file_approvals
            or any(request.path.startswith(grant) for grant in self.path_grants)
        ):
            return PermissionDecision(True, False, "path-grant")

        if self.mode is ApprovalMode.AUTO_SAFE and request.risk in (Risk.NONE, Risk.LOW):
            return PermissionDecision(True, False, "auto-safe")

        return PermissionDecision(False, True, "manual-approval")

    def recheck_after_edit(self, request: PermissionRequest) -> PermissionDecision:
        """审批中被修改过的输入必须**重新**跑全部 deny 门（D5）。"""
        return self.authorize(request)

    def remember_bash(self, prefix: str) -> None:
        if prefix.strip():
            self.bash_prefixes.add(prefix.strip())

    def remember_file(self, path: str) -> None:
        if path.strip():
            self.file_approvals.add(path)

    def grant_path(self, path: str) -> None:
        if path.strip():
            self.path_grants.add(path)
