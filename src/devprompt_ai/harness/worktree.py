"""工作副本（K4）：写工在独立 git worktree 里改，只回传 diff。

本模块只构造参数与路径，真正的执行走 `CommandRunner`（MUST-13：异步子进程、
超时、禁 shell）。git 不可用时调用方就地降级到只读建议。
"""

from __future__ import annotations

import posixpath
from typing import Final

_WORKTREE_DIR: Final[str] = ".devprompt-worktrees"


def branch_name(order_id: str) -> str:
    return f"devprompt-hands-{order_id[:8]}"


def worktree_path(repo_root: str, order_id: str) -> str:
    return posixpath.join(repo_root.replace("\\", "/"), _WORKTREE_DIR, order_id[:8])


def create_args(repo_root: str, order_id: str, *, base: str = "HEAD") -> list[str]:
    return [
        "git",
        "-C",
        repo_root,
        "worktree",
        "add",
        "-b",
        branch_name(order_id),
        worktree_path(repo_root, order_id),
        base,
    ]


def remove_args(repo_root: str, order_id: str) -> list[str]:
    return [
        "git",
        "-C",
        repo_root,
        "worktree",
        "remove",
        "--force",
        worktree_path(repo_root, order_id),
    ]


def diff_args(repo_root: str, order_id: str, *, base: str = "HEAD") -> list[str]:
    return ["git", "-C", repo_root, "diff", "--binary", f"{base}...{branch_name(order_id)}"]


def merge_args(repo_root: str, order_id: str) -> list[str]:
    return ["git", "-C", repo_root, "merge", "--squash", branch_name(order_id)]
