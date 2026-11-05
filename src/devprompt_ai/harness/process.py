"""harness 层子进程 I/O：Protocol 实现（MUST-06 落点）与 F-101 符号表编排。

run_command 通道在 common/process.py（MUST-13 唯一子进程通道）；
本模块实现 domain/retrieval/ports.py 声明的 CommandRunner / FileReader，
并提供 SymbolTableProvider（ctags 编排 + TTL 1h 进程内缓存，MUST-14）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, replace

from devprompt_ai.common.process import run_command
from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner
from devprompt_ai.domain.retrieval.symbols import (
    EXCLUDED_DIRS,
    build_ctags_args,
    cache_key,
    parse_ctags_output,
)

logger = logging.getLogger("devprompt.cache")

SYMBOL_TABLE_TTL = 3600.0  # MUST-14：符号表缓存 TTL 1 小时


class LocalCommandRunner:
    """CommandRunner 的本地实现：转发 common.process.run_command。"""

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        return await run_command(
            args, timeout=timeout, allowed_exit_codes=allowed_exit_codes, cwd=cwd
        )


class LocalFileReader:
    """FileReader 的本地实现（路径规范化由调用方在 domain 层完成）。

    阻塞 I/O 经 asyncio.to_thread 卸载到线程池（MUST-13：异步路径禁阻塞调用）。
    """

    async def read(self, path: str) -> str:
        return await asyncio.to_thread(self._read_text, path)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(os.path.isfile, path)

    def _read_text(self, path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()


@dataclass(frozen=True, slots=True)
class SymbolTableResult:
    """F-101 对外返回：符号表 + 本次是否缓存命中 + 代码快照指纹。

    ``cache_key`` 是 root + 全量 mtime 的摘要（``symbols.cache_key``）。多轮继承用它
    判定取证是否过期：指纹变了说明代码改过，继承的 facts 不能再当证据（2026-11-04）。
    """

    symbols: list[Symbol]
    cache_hit: bool
    cache_key: str = ""


def _to_rel(path: str, root: str) -> str:
    """将 ctags 输出路径归一为仓库相对 POSIX 路径（Symbol 契约要求）。

    root 可能是相对路径（如 `.` 或 `eval/recall/mock-x`），与 ctags 的 cwd 相对输出一致；
    relpath 失败（如跨盘符）时保留原值兜底，不中断符号表构建。
    """
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path


class SymbolTableProvider:
    """F-101 编排：ctags 调用 + 解析 + 进程内缓存（键含 mtime 摘要，TTL 1h）。

    增量策略采用 SHOULD-04「惰性优于定时」：访问时以 mtime 摘要探测变更，
    变更即整表重建（符号表重建成本低，不做逐文件 diff）。
    """

    def __init__(self, runner: CommandRunner, ttl_seconds: float = SYMBOL_TABLE_TTL) -> None:
        self._runner = runner
        self._ttl = ttl_seconds
        self._cache_key: str | None = None
        self._cache_symbols: list[Symbol] | None = None
        self._cached_at: float = 0.0
        self.mtime_digest_override: str | None = None  # 测试注入点
        self.calls_args: list[list[str]] = []  # 测试观测点

    def _collect_mtimes(self, root: str) -> list[tuple[str, int]]:
        entries: list[tuple[str, int]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                entries.append((os.path.relpath(fp, root), st.st_mtime_ns))
        return entries

    def _current_key(self, root: str) -> str:
        if self.mtime_digest_override is not None:
            return cache_key(root, [("override", hash(self.mtime_digest_override))])
        return cache_key(root, self._collect_mtimes(root))

    async def get(self, root: str) -> SymbolTableResult:
        now = time.monotonic()
        key = self._current_key(root)
        if (
            self._cache_symbols is not None
            and self._cache_key == key
            and (now - self._cached_at) < self._ttl
        ):
            logger.info("cache.hit", extra={"what": "symbol_table", "root": root})
            return SymbolTableResult(
                symbols=self._cache_symbols or [], cache_hit=True, cache_key=key
            )

        args = build_ctags_args(root)
        self.calls_args.append(args)
        try:
            raw = await self._runner.run(args, timeout=30.0)
        except Exception:
            # 老版 ctags 不认 `--fields=+n+{signature}` 会直接失败（未知字段名）。
            # 去掉签名重试一次：签名只是排序的增强信息，不该让整个符号表不可用。
            # shortcut: 仅在带签名参数失败时降级；代价是排序少了签名（退化为改造前行为）。
            # 升级路径：若 ctags 支持探测命令，可先探测再决定是否带签名，省一次重试。
            args = build_ctags_args(root, with_signature=False)
            self.calls_args.append(args)
            raw = await self._runner.run(args, timeout=30.0)
        symbols = [replace(s, path=_to_rel(s.path, root)) for s in parse_ctags_output(raw)]
        self._cache_key = key
        self._cache_symbols = symbols
        self._cached_at = now
        logger.info("cache.miss", extra={"what": "symbol_table", "root": root})
        return SymbolTableResult(symbols=symbols, cache_hit=False, cache_key=key)
