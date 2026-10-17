"""跨平台子进程编排器：Windows shell 差异集中化 + 串并行步骤编排。

借鉴 prompt-optimizer `scripts/pnpm-runner.js` + `scripts/run-many.js`。

## 为什么需要 Windows 专门处理

Windows 上 `subprocess` **不能直接执行 `.cmd`/`.bat`**（pnpm / npm / npx 都是批处理
文件），必须经 `cmd.exe`。而 `.exe`（uv / python / node / ruff / mypy）可以直接执行。

因此本模块按**文件后缀**而非平台分支来决定是否包一层 shell：
- `resolve_tool()` 解析出真实路径 -> `.exe` 直接执行（Windows 与 Unix 同一形态）；
- `.cmd` / `.bat` -> Windows 下用 `ComSpec /d /s /c` 包装，Unix 下直接执行。

`/d` 禁用 AutoRun 注册表项（`.cmd` 里的 autorun 会污染非交互执行）；`/s` 修正带空格
路径的引号剥离；`shell=False` 显式声明，避免多一层 shell 解释
（prompt-optimizer 实测：`script-shell=pwsh.exe` 会把 `--format cjs,esm` 的逗号参数
拆成数组，esbuild 报 `Invalid value "cjs esm"`）。

零第三方依赖（MUST-04 第 1–2 级：仅标准库 subprocess/shutil）。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

#: 并行默认并发上限（`uv sync` 与 `pnpm install` 同时跑会争抢 IO 与文件锁）
DEFAULT_MAX_PARALLEL = 2

#: 必须经 shell 包装的后缀（Windows 不可直接执行）
SHELL_REQUIRED_SUFFIXES = (".cmd", ".bat")

#: 找不到工具时的修复建议。**只给工具名与命令，绝不涉及任何环境变量值**（MUST-19）
_MISSING_TOOL_HINTS: dict[str, str] = {
    "uv": "安装 uv：https://docs.astral.sh/uv/",
    "pnpm": "安装 pnpm ^10.15（技术栈 §6.3）；禁止用 npm -g 装项目依赖（MUST-24）",
    "node": "安装 Node.js ^20.19 / ^22.12（技术栈 §6.3）",
}


@dataclass(frozen=True)
class RunnerSpec:
    """一次子进程调用的完整规格（平台差异的唯一载体）。"""

    command: str
    prefix: tuple[str, ...]
    shell: bool


def get_runner_spec(
    tool: str, platform: str | None = None, env: dict[str, str] | None = None
) -> RunnerSpec:
    """返回该平台上调用 `tool` 的 spec（纯函数，可单测）。

    `ComSpec || COMSPEC` 双写兜底：环境变量键名大小写在不同 shell 下不一致。
    """
    plat = sys.platform if platform is None else platform
    environ = {} if env is None else env
    if plat == "win32":
        return RunnerSpec(
            command=environ.get("ComSpec") or environ.get("COMSPEC") or "cmd.exe",
            prefix=("/d", "/s", "/c", tool),
            shell=False,
        )
    return RunnerSpec(command=tool, prefix=(), shell=False)


def resolve_tool(tool: str) -> str:
    """在 PATH 中解析可执行文件的真实路径；找不到时抛带修复建议的错误。"""
    found = shutil.which(tool)
    if found:
        return found
    hint = _MISSING_TOOL_HINTS.get(tool, "确认该工具已安装并在 PATH 中")
    raise FileNotFoundError(f"找不到可执行文件 {tool!r}：{hint}")


def build_argv(
    step: str, platform: str | None = None, env: dict[str, str] | None = None
) -> list[str]:
    """把 `"uv build"` 这样的步骤字符串组装为可直接 execve 的 argv。

    仅支持「工具名 + 参数」形态，shell 元字符（`&`、`|`、`>`）一律当普通参数，
    因此不存在注入面；调用方只应传入本仓库自有的可信步骤。
    """
    argv = step.split()
    if not argv:
        raise ValueError(f"空步骤：{step!r}")
    tool, rest = argv[0], argv[1:]
    resolved = resolve_tool(tool)
    plat = sys.platform if platform is None else platform
    if plat == "win32" and resolved.lower().endswith(SHELL_REQUIRED_SUFFIXES):
        spec = get_runner_spec(resolved, platform=plat, env=env)
        return [spec.command, *spec.prefix, *rest]
    return [resolved, *rest]


def run_step(
    step: str,
    *,
    dry_run: bool = False,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """执行单步，返回退出码。子进程输出直通父终端（Windows 下 Ctrl+C 行为一致）。"""
    if dry_run:
        print(f"[dry-run] {step}")
        return 0
    command = build_argv(step, env=env)
    print(f"[run] {step}")
    return subprocess.run(command, cwd=cwd, env=env, check=False, shell=False).returncode


def run_many(
    steps: Sequence[str],
    *,
    parallel: bool = False,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    dry_run: bool = False,
) -> int:
    """按声明顺序串行执行，或以受限并发并行执行。任一失败即返回非零。"""
    if not steps:
        return 0
    if not parallel:
        for step in steps:
            code = run_step(step, dry_run=dry_run)
            if code != 0:
                print(f"[fail] 步骤失败（exit={code}）：{step}", file=sys.stderr)
                return code
        return 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        futures = {pool.submit(run_step, s, dry_run=dry_run): s for s in steps}
        for future in concurrent.futures.as_completed(futures):
            step = futures[future]
            try:
                code = future.result()
            except Exception as exc:  # noqa: BLE001 - 编排层须汇总任意子进程异常
                print(f"[fail] 步骤异常：{step} -> {exc}", file=sys.stderr)
                return 1
            if code != 0:
                print(f"[fail] 步骤失败（exit={code}）：{step}", file=sys.stderr)
                return code
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """纯函数化参数解析（便于单测）。"""
    parser = argparse.ArgumentParser(
        prog="runner.py", description="跨平台步骤编排器（uv / pnpm / node）"
    )
    parser.add_argument("--parallel", "-p", action="store_true", help="并行执行（默认串行）")
    parser.add_argument(
        "--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL, help="并行并发上限"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    parser.add_argument("steps", nargs="+", help="步骤，形如 'uv build'")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_many(
        args.steps, parallel=args.parallel, max_parallel=args.max_parallel, dry_run=args.dry_run
    )


if __name__ == "__main__":
    raise SystemExit(main())
