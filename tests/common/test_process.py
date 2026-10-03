"""common/process.py 测试：跨平台用 sys.executable -c 模拟子进程。"""

import sys

import pytest

from devprompt_ai.common.process import ProcessTimeoutError, run_command


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
