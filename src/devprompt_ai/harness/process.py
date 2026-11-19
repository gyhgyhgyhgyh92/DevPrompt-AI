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
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from devprompt_ai.common.process import run_command, run_command_stream
from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.retrieval.ports import CommandRunner
from devprompt_ai.domain.retrieval.symbols import (
    EXCLUDED_DIRS,
    build_ctags_args,
    build_export_scan_args,
    cache_key,
    parse_ctags_output,
    parse_export_scan_output,
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

    async def run_stream(
        self,
        args: list[str],
        *,
        on_line: Callable[[str], Awaitable[None]],
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        """流式变体（2026-11-15）：逐行回调，供展示层做增量呈现。"""
        return await run_command_stream(
            args,
            on_line=on_line,
            timeout=timeout,
            allowed_exit_codes=allowed_exit_codes,
            cwd=cwd,
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

    def __init__(
        self, runner: CommandRunner, ttl_seconds: float = SYMBOL_TABLE_TTL, capacity: int = 4
    ) -> None:
        self._runner = runner
        self._ttl = ttl_seconds
        self._capacity = max(1, capacity)
        # 多槽 LRU（2026-11-19）：单槽会让多项目交替时互相驱逐，每次切回都全量重建。
        self._slots: OrderedDict[str, tuple[list[Symbol], float]] = OrderedDict()
        # 以下三项保留为「最近一次访问」的兼容投影（测试与诊断仍读取）。
        self._cache_key: str | None = None
        self._cache_symbols: list[Symbol] | None = None
        self._cached_at: float = 0.0
        self.mtime_digest_override: str | None = None  # 测试注入点
        self.calls_args: list[list[str]] = []  # 测试观测点
        #: ctags 是否支持 `{signature}` 字段：None=未知（首次尝试），False=已确认不支持（不再重试）
        self._signature_ok: bool | None = None

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
        cached = self._slots.get(key)
        if cached is not None and (now - cached[1]) < self._ttl:
            self._slots.move_to_end(key)
            self._cache_key, self._cache_symbols, self._cached_at = key, cached[0], cached[1]
            logger.info("cache.hit", extra={"what": "symbol_table", "root": root})
            return SymbolTableResult(symbols=cached[0], cache_hit=True, cache_key=key)

        # 老版 ctags 不认 `--fields=+n+{signature}`（未知字段名）会直接失败：签名只是排序的
        # 增强信息，不该让整个符号表不可用。首次失败后记住「本进程不支持签名」，后续直接不带，
        # 避免每次刷新缓存都白跑一次失败调用（2026-11-07 清理 shortcut）。
        args = build_ctags_args(root, with_signature=self._signature_ok is not False)
        self.calls_args.append(args)
        try:
            raw = await self._runner.run(args, timeout=30.0)
        except Exception:
            if self._signature_ok is False:
                raise
            self._signature_ok = False
            logger.info("symbols.signature_unsupported", extra={"what": "ctags"})
            args = build_ctags_args(root, with_signature=False)
            self.calls_args.append(args)
            raw = await self._runner.run(args, timeout=30.0)
        symbols = [replace(s, path=_to_rel(s.path, root)) for s in parse_ctags_output(raw)]
        # ctags 对 TSX 存在漏标（见 symbols.build_export_scan_args 文档）：补扫顶层 export
        # 声明并按 (path, name) 去重合并。补扫失败不阻断主链——ctags 结果仍可用。
        try:
            scan_raw = await self._runner.run(build_export_scan_args("."), timeout=30.0, cwd=root)
        except Exception:  # noqa: BLE001 - 兜底增强项，失败退回纯 ctags 结果
            logger.info("symbols.export_scan_failed", extra={"what": "rg"})
        else:
            known = {(s.path, s.name) for s in symbols}
            for extra in parse_export_scan_output(scan_raw):
                if (extra.path, extra.name) not in known:
                    known.add((extra.path, extra.name))
                    symbols.append(extra)
        self._slots[key] = (symbols, now)
        self._slots.move_to_end(key)
        while len(self._slots) > self._capacity:
            self._slots.popitem(last=False)
        self._cache_key = key
        self._cache_symbols = symbols
        self._cached_at = now
        logger.info("cache.miss", extra={"what": "symbol_table", "root": root})
        return SymbolTableResult(symbols=symbols, cache_hit=False, cache_key=key)
