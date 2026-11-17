"""C 档可验证锚点的后端校验（2026-11-06 U-2，纯函数、零 I/O）。

C 档承诺「路径与行号来自真实取证，可直接 ``rg -n`` 复核」——此前只有 prompt 层约束，
正文里的 ``路径:行号`` 从未被机器核对（U-2 业主裁定补上）。判定分三态：
有效 / 明确无效（文件不存在或行号越界 → 降 B + 披露）/ 判不清（绝对路径、读取失败等，
保守不降档，避免误伤）。

I/O 经注入的逐锚点判定进入（MUST-06）：调用方用 FileReader 拼 project_root 后给出
``True / False / None``，本模块只做抽取与聚合。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

#: ``路径:行号``——路径必须带扩展名（避免「注意:123」这类误伤），行号 1~6 位；
#: 负向后瞻防止从盘符/URL 的路径中段起配（``C:\repo\b.py:2`` / ``…example.com/a.py:1``）。
_ANCHOR_RE: Final = re.compile(r"`?(?<![.\w\\/])([\w][\w./\\-]*\.[A-Za-z0-9]{1,8}):(\d{1,6})`?")
#: 盘符 / 根起始 / 家目录 / URL → 无法在项目内核验，判不清。
_NON_PROJECT_RE: Final = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~|https?://)")


@dataclass(frozen=True, slots=True)
class Anchor:
    """方案正文里的一处「路径:行号」引用（仓库相对形态）。"""

    path: str
    line: int


@dataclass(frozen=True, slots=True)
class AnchorReport:
    """一次锚点核验的聚合结果（不含绝对路径，MUST-19）。"""

    total: int
    invalid: tuple[str, ...]


def is_project_relative(path: str) -> bool:
    """路径形态可否在项目内核验：排除盘符、根起始、家目录与 URL。"""
    return _NON_PROJECT_RE.match(path) is None


def extract_anchors(body: str) -> tuple[Anchor, ...]:
    """从方案正文抽取全部「路径:行号」锚点（去重保序）。"""
    anchors: list[Anchor] = []
    seen: set[tuple[str, int]] = set()
    for match in _ANCHOR_RE.finditer(body):
        path = match.group(1)
        line = int(match.group(2))
        if not is_project_relative(path):
            continue
        key = (path, line)
        if key not in seen:
            seen.add(key)
            anchors.append(Anchor(path=path, line=line))
    return tuple(anchors)


def verify_anchors(verdicts: Sequence[tuple[Anchor, bool | None]]) -> AnchorReport:
    """聚合逐锚点判定：``False`` 计入 invalid，``None``（判不清）与 ``True`` 不降档。"""
    invalid: list[str] = []
    for anchor, ok in verdicts:
        if ok is False:
            invalid.append(f"{anchor.path}:{anchor.line}")
    return AnchorReport(total=len(verdicts), invalid=tuple(invalid))
