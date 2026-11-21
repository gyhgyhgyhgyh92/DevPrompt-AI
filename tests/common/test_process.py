"""common/process.py 测试：跨平台用 sys.executable -c 模拟子进程。"""

import sys

import pytest

from devprompt_ai.common.process import ProcessTimeoutError, run_command, run_command_stream


async def test_run_command_returns_stdout() -> None:
    out = await run_command([sys.executable, "-c", "print('hello-rg')"])
    assert "hello-rg" in out


async def test_run_command_allowed_exit_codes() -> None:
    # 退出码 2 不在允许集 → 抛错；允许集内 → 正常返回
    out = await run_command(
        [sys.executable, "-c", "import sys; sys.exit(2)"], allowed_exit_codes=frozenset({2})
    )
    assert out == ""


async def test_run_command_unexpected_exit_raises() -> None:
    from devprompt_ai.common.process import ProcessError

    with pytest.raises(ProcessError):
        await run_command([sys.executable, "-c", "import sys; sys.exit(2)"])


async def test_run_command_timeout_kills() -> None:
    with pytest.raises(ProcessTimeoutError):
        await run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)


async def test_run_command_stream_delivers_lines_incrementally() -> None:
    """流式（2026-11-15）：on_line 在执行期间逐行收到 stdout，不是结束后一次性。"""
    lines: list[str] = []

    async def on_line(line: str) -> None:
        lines.append(line)

    out = await run_command_stream(
        [sys.executable, "-c", "print('a'); print('b')"], on_line=on_line
    )

    assert lines == ["a", "b"]
    assert out.replace("\r\n", "\n") == "a\nb\n"


async def test_run_command_stream_drains_stderr_without_deadlock() -> None:
    """stderr 大量输出也不能挂死：管道写满会阻塞子进程，必须并发消费 stderr。"""
    out = await run_command_stream(
        [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000); print('done')"],
        timeout=20.0,
    )

    assert "done" in out


async def test_run_command_stream_timeout_still_raises() -> None:
    with pytest.raises(ProcessTimeoutError):
        await run_command_stream([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)
