"""角色 profile（K6）：决定工具集、预算与是否可写。

未知 profile 一律返回 None（fail-closed），调用方据此拒绝派发，而不是给全量工具。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    allowed_tools: frozenset[str]
    budget_ms: int = 60_000
    write: bool = False


_READ_TOOLS: Final[frozenset[str]] = frozenset({"read_file", "grep", "glob", "bash"})
_WRITE_TOOLS: Final[frozenset[str]] = _READ_TOOLS | frozenset({"write_file", "edit_file"})

PROFILES: Final[dict[str, Profile]] = {
    "code_scout": Profile("code_scout", _READ_TOOLS, 60_000),
    "verifier": Profile("verifier", _READ_TOOLS, 90_000),
    "patcher": Profile("patcher", _WRITE_TOOLS, 120_000, write=True),
}


def get_profile(name: str) -> Profile | None:
    return PROFILES.get(name)


def allowed_tools(name: str) -> frozenset[str]:
    profile = get_profile(name)
    return profile.allowed_tools if profile is not None else frozenset()
