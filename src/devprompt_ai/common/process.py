"""异步子进程执行封装（MUST-13 的唯一通道）。

规则：一律 asyncio.create_subprocess_exec；禁 shell=True；必须设超时（默认 10 秒）；
超时/异常路径 kill() + await wait() 防僵尸进程；输出统一 UTF-8 errors=replace。
"""

from __future__ import annotations

import asyncio

DEFAULT_TIMEOUT = 10.0
_ENCODING = "utf-8"

DEFAULT_ALLOWED_EXIT_CODES = frozenset({0})


class ProcessError(RuntimeError):
    """子进程非零退出（且退出码不在 allowed_exit_codes 内）。"""

    def __init__(self, args: list[str], code: int, stderr: str) -> None:
        super().__init__(f"命令失败 exit={code}: {' '.join(args)}\nstderr: {stderr[:500]}")
        self.code = code


class ProcessTimeoutError(RuntimeError):
    """子进程超时（已 kill）。"""


async def run_command(
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allowed_exit_codes: frozenset[int] = DEFAULT_ALLOWED_EXIT_CODES,
    cwd: str | None = None,
) -> str:
    """执行外部命令并返回 stdout 文本。exit 码不在允许集时抛 ProcessError。"""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        proc.kill()
        await proc.wait()  # 僵尸进程清理（MUST-13）
        raise ProcessTimeoutError(f"命令超时({timeout}s): {' '.join(args)}") from None

    stdout = stdout_b.decode(_ENCODING, errors="replace")
    stderr = stderr_b.decode(_ENCODING, errors="replace")
    code = proc.returncode if proc.returncode is not None else -1
    if code not in allowed_exit_codes:
        raise ProcessError(args, code, stderr)
    return stdout
