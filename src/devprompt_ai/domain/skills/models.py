"""Skill 纯数据（2026-11-21）：两形态共用一套元数据，零 I/O。

形态：
- `dir`：扫描本地目录下的 `SKILL.md`（兼容 Claude/CodeBuddy 规范），正文按需读取；
- `custom`：界面新建，正文存 SQLite，`path` 为空。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SkillSource = Literal["dir", "custom"]


@dataclass(frozen=True, slots=True)
class SkillMeta:
    """技能元数据（列表与匹配只用它，不读正文——渐进式披露）。"""

    name: str
    description: str = ""
    source: SkillSource = "dir"
    path: str = ""
    domains: tuple[str, ...] = ()
    skill_id: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "path": self.path,
            "domains": list(self.domains),
            "skill_id": self.skill_id,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class Skill:
    """元数据 + 正文；正文由调用方按需加载（目录来源读文件，自定义读库）。"""

    meta: SkillMeta
    body: str = ""
    extras: tuple[str, ...] = field(default_factory=tuple)
