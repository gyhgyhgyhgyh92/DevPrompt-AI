"""异步子进程执行封装（MUST-13 的唯一通道）。

规则：一律 asyncio.create_subprocess_exec；禁 shell=True；必须设超时（默认 10 秒）；
超时/异常路径 kill() + await wait() 防僵尸进程；输出统一 UTF-8 errors=replace。
可执行文件解析带兜底（shutil.which → DPROMPT_<NAME>_PATH → WinGet/编辑器内置工具
目录扫描），保证「本地工具即开即用」——用户终端无需手工配置 PATH。
"""

from __future__ import annotations

import asyncio
import glob
import os
import shutil
from pathlib import Path

DEFAULT_TIMEOUT = 10.0
_ENCODING = "utf-8"

DEFAULT_ALLOWED_EXIT_CODES = frozenset({0})

_resolved_cache: dict[str, str] = {}

_INSTALL_HINTS = {
    "rg": "winget install BurntSushi.ripgrep.MSVC",
    "ctags": "winget install universal-ctags.ctags",
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
        hint = _INSTALL_HINTS.get(name, "")
        message = f"未找到可执行文件 {name}。"
        if hint:
            message += f" 安装：{hint}"
        message += f" 或设置环境变量 DPROMPT_{name.upper()}_PATH 指向其完整路径。"
        super().__init__([name], 9001, message)


def _candidate_dirs() -> list[Path]:
    """已知工具安装根：WinGet 包目录 + 本机程序目录（VSCode 系编辑器内置工具布局）。"""
    local = os.environ.get("LOCALAPPDATA", "")
    dirs: list[Path] = []
    if local:
        dirs.append(Path(local) / "Microsoft" / "WinGet" / "Packages")
        dirs.append(Path(local) / "Programs")
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
    if os.name == "nt":
        exe = f"{name}.exe"
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
