"""检索层 I/O 能力声明（MUST-06：domain 只依赖 Protocol，实现在 harness/process.py）。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CommandRunner(Protocol):
    """执行外部命令（ripgrep / ctags）。"""

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        """返回 stdout 文本；超时/非允许退出码由实现抛错。"""
        ...


@runtime_checkable
class FileReader(Protocol):
    """读取文件内容与存在性检查。"""

    async def read(self, path: str) -> str:
        """读取文本（UTF-8）。"""
        ...

    async def exists(self, path: str) -> bool:
        """文件存在性。"""
        ...
