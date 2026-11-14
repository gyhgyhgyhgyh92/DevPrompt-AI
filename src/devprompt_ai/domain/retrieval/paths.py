"""仓库相对路径的安全拼接（MUST-20 路径穿越防护）。

纯函数、零 I/O：只做字符串规范化，不触文件系统（MUST-06 允许 ``domain/`` 持有）。

为什么要单独成模块：``locate`` / ``facts`` / ``service`` 三处都要把「仓库相对路径」
拼到项目根上。此前各自直接 ``posixpath.join(root, rel)``，一旦符号表被畸形仓库污染
（ctags 输出 ``../../etc/passwd``），读取就会逃出项目根。集中到一处后，判据只有一份。
"""

from __future__ import annotations

import posixpath
import re

#: Windows 盘符前缀（`C:` / `D:/`）：相对路径不该带它。
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _norm(path: str) -> str:
    """统一成正斜杠并规范化（折叠 ``.`` 与 ``..``）。"""
    return posixpath.normpath(path.replace("\\", "/"))


def safe_join(root: str, rel: str) -> str:
    """把仓库相对路径拼到根上；越界或非法时返回空串。

    调用方约定：空串等价于「该路径不可用」，按「文件不存在」处理——这样越界请求
    与真实的缺失路径走同一条失败分支，不额外制造新的错误类型。

    拒绝三类：
    1. 绝对路径（``/etc/passwd``）
    2. 带盘符的路径（``C:/Windows``）
    3. 规范化后逃逸出 ``root``（``../../etc``）——注意是**规范化之后**再比较，
       否则 ``src/../../x`` 这类拼接后的逃逸会被漏掉。

    ``root`` 为空（"." 或 ""）时没有边界可依，退化为拒绝任何以 ``..`` 开头的相对路径。
    """
    rel_posix = rel.replace("\\", "/").strip()
    if not rel_posix:
        return ""
    if rel_posix.startswith("/") or _DRIVE_RE.match(rel_posix):
        return ""

    root_posix = root.replace("\\", "/").strip()
    if root_posix in ("", "."):
        normalized = _norm(rel_posix)
        return "" if normalized == ".." or normalized.startswith("../") else normalized

    root_norm = _norm(root_posix)
    joined = _norm(posixpath.join(root_norm, rel_posix))
    if joined == root_norm:
        # 相对路径指回根本身（如 "."），不是文件，按不可用处理。
        return ""
    if not joined.startswith(root_norm + "/"):
        return ""
    return joined
