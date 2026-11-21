"""异步子进程执行封装（MUST-13 的唯一通道）。

规则：一律 asyncio.create_subprocess_exec；禁 shell=True；必须设超时（默认 10 秒）；
超时/异常路径 kill() + await wait() 防僵尸进程；输出统一 UTF-8 errors=replace。
可执行文件解析带兜底（shutil.which → DPROMPT_<NAME>_PATH → 平台常见安装目录扫描），
保证「本地工具即开即用」——用户终端无需手工配置 PATH。
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
_ENCODING = "utf-8"

DEFAULT_ALLOWED_EXIT_CODES = frozenset({0})

_resolved_cache: dict[str, str] = {}

#: 安装指引按平台给出：Windows 用 winget，macOS 用 brew，Linux 用 apt
_INSTALL_HINTS = {
    "rg": {
        "win32": "winget install BurntSushi.ripgrep.MSVC",
        "darwin": "brew install ripgrep",
        "linux": "apt install ripgrep",
    },
    "ctags": {
        "win32": "winget install universal-ctags.ctags",
        "darwin": "brew install universal-ctags",
        "linux": "apt install universal-ctags",
    },
}


class ProcessError(RuntimeError):
    """子进程非零退出（且退出码不在 allowed_exit_codes 内）。"""

    def __init__(self, args: list[str], code: int, stderr: str) -> None:
        super().__init__(f"命令失败 exit={code}: {' '.join(args)}\nstderr: {stderr[:500]}")
        self.code = code
        #: 原始 stderr（截断 500 字）：观测层要把它脱敏后展示成失败卡片（2026-11-04）
        self.stderr = stderr[:500]


class ProcessTimeoutError(RuntimeError):
    """子进程超时（已 kill）。"""


class ExecutableNotFoundError(ProcessError):
    """可执行文件在 PATH 与已知兜底位置均未找到（带安装指引）。"""

    def __init__(self, name: str) -> None:
        self.missing = name
        hint = _INSTALL_HINTS.get(name, {}).get(sys.platform, "")
        message = f"未找到可执行文件 {name}。"
        if hint:
            message += f" 安装：{hint}"
        message += f" 或设置环境变量 DPROMPT_{name.upper()}_PATH 指向其完整路径。"
        super().__init__([name], 9001, message)


def _candidate_dirs() -> list[Path]:
    """已知工具安装根：Windows 的 WinGet/程序目录，macOS 与 Linux 的常见前缀。

    GUI 应用（桌面壳）启动时的 PATH 往往不含 Homebrew / /usr/local 等目录，
    故这些位置必须显式兜底，否则桌面端找不到 rg/ctags。
    """
    dirs: list[Path] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            dirs.append(Path(local) / "Microsoft" / "WinGet" / "Packages")
            dirs.append(Path(local) / "Programs")
    else:
        dirs.extend(
            [
                Path("/opt/homebrew/bin"),  # macOS Apple Silicon Homebrew
                Path("/opt/homebrew/sbin"),
                Path("/usr/local/bin"),  # macOS Intel Homebrew / Linux 自编译
                Path("/usr/local/sbin"),
                Path("/usr/bin"),
                Path("/bin"),
                Path.home() / ".cargo" / "bin",
                Path.home() / ".local" / "bin",
            ]
        )
    return [d for d in dirs if d.is_dir()]


def _resolve_executable(name: str) -> str:
    """解析可执行文件：which → DPROMPT_<NAME>_PATH → 兜底目录递归扫描（结果缓存）。"""
    hit = shutil.which(name)
    if hit:
        return hit
    if name in _resolved_cache:
        return _resolved_cache[name]
    env_val = os.environ.get(f"DPROMPT_{name.upper()}_PATH")
    if env_val and Path(env_val).is_file():
        _resolved_cache[name] = env_val
        return env_val
    #: Windows 可执行文件带 .exe；POSIX 不带后缀
    exe = f"{name}.exe" if os.name == "nt" else name
    for base in _candidate_dirs():
        hits = sorted(glob.glob(str(base / "**" / exe), recursive=True))
        if hits:
            _resolved_cache[name] = hits[0]
            return hits[0]
    return name  # 未命中：交由 CreateProcess 抛出，由 run_command 转友好错误


async def run_command(
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allowed_exit_codes: frozenset[int] = DEFAULT_ALLOWED_EXIT_CODES,
    cwd: str | None = None,
) -> str:
    """执行外部命令并返回 stdout 文本。exit 码不在允许集时抛 ProcessError。"""
    return await run_command_stream(
        args,
        on_line=None,
        timeout=timeout,
        allowed_exit_codes=allowed_exit_codes,
        cwd=cwd,
    )


async def run_command_stream(
    args: list[str],
    *,
    on_line: Callable[[str], Awaitable[None]] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    allowed_exit_codes: frozenset[int] = DEFAULT_ALLOWED_EXIT_CODES,
    cwd: str | None = None,
) -> str:
    """执行外部命令并返回 stdout 文本；``on_line`` 在执行期间逐行收到 stdout。

    与 :func:`run_command` 同源（后者是本函数的 ``on_line=None`` 特例），退出码与
    超时语义完全一致。

    **stderr 必须并发消费**：逐行读 stdout 时若无人读 stderr，管道写满会让子进程
    阻塞（rg 输出大量告警即触发），故 stderr 由独立 task 持续 drain。
    """
    # 测试路由键约定（F-103/F-104）：domain 层在 rg 参数后追加 --route-key=<键> 供测试 Fake 路由，
    # 真实进程不可见，转发前过滤
    args = [a for a in args if not a.startswith("--route-key=")]
    resolved = _resolve_executable(args[0])
    if resolved != args[0]:
        args = [resolved, *args[1:]]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        # WinError 2 的友好化：给出安装/配置指引而非裸堆栈（真实用户终端实测暴露）
        raise ExecutableNotFoundError(args[0]) from exc

    async def _drain_stderr() -> bytes:
        assert proc.stderr is not None
        return await proc.stderr.read()

    stderr_task = asyncio.create_task(_drain_stderr())
    stdout_parts: list[str] = []

    async def _pump_stdout() -> None:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return
            line = raw.decode(_ENCODING, errors="replace")
            stdout_parts.append(line)
            if on_line is None:
                continue
            try:
                await on_line(line.rstrip("\r\n"))
            except Exception:  # noqa: BLE001 - 展示层异常不得中断真实命令
                logger.debug("process.on_line_failed", exc_info=True)

    try:
        await asyncio.wait_for(_pump_stdout(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        proc.kill()
        await proc.wait()  # 僵尸进程清理（MUST-13）
        stderr_task.cancel()
        raise ProcessTimeoutError(f"命令超时({timeout}s): {' '.join(args)}") from None

    stderr_b = await stderr_task
    stdout = "".join(stdout_parts)
    stderr = stderr_b.decode(_ENCODING, errors="replace")
    # stdout 读到 EOF 不等于进程已退出：显式 wait 才能拿到真实退出码
    await proc.wait()
    code = proc.returncode if proc.returncode is not None else -1
    if code not in allowed_exit_codes:
        raise ProcessError(args, code, stderr)
    return stdout
