"""F-502 L2 Git notes 测试（Fake runner 路由，无真实 git）。

注：不复用 tests/domain/retrieval/fakes.py——tests/ 无 __init__.py，pytest prepend
模式只插入本文件所在目录，独立运行 tests/memory/ 时该模块不可导入（已实证
ModuleNotFoundError）。故按其路由键约定内联同款 Fake：构造签名
dict[tuple[str, str], str]、按「命令首词 + --route-key=」路由、未命中返回空串。
"""

import pytest

from devprompt_ai.domain.retrieval.ports import CommandRunner
from devprompt_ai.memory.project_notes import (
    MAX_NOTE_BYTES,
    ensure_push_config,
    init_note,
    read_notes,
    write_note,
)

_OK = {"notes-list": "abc123 refs/heads/main\n", "notes-show": "规范内容"}


class FakeCommandRunner(CommandRunner):
    """与 tests/domain/retrieval/fakes.py 同约定的假 runner（无真实进程）。"""

    def __init__(self, routes: dict[tuple[str, str], str]) -> None:
        self._routes = routes
        self.calls: list[list[str]] = []

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        self.calls.append(args)
        word = args[0] if args else ""
        key = next((a.split("=", 1)[1] for a in args if a.startswith("--route-key=")), "")
        return self._routes.get((word, key), "")


def _runner(extra: dict[str, str] | None = None) -> FakeCommandRunner:
    routes = dict(_OK)
    routes.update(extra or {})
    return FakeCommandRunner({("git", k): v for k, v in routes.items()})


async def test_read_notes_parses_objects() -> None:
    notes = await read_notes("C:/repo", _runner())
    assert notes == [("abc123", "规范内容")]


async def test_read_notes_empty_when_no_notes() -> None:
    runner = _runner({"notes-list": ""})
    assert await read_notes("C:/repo", runner) == []


async def test_write_note_within_limit() -> None:
    runner = _runner({"notes-add": ""})
    await write_note("C:/repo", "规范 v1", runner)
    assert runner.calls[0][0] == "git"
    assert "--ref" in runner.calls[0] and "devprompt" in runner.calls[0]


async def test_write_note_over_8kb_rejected() -> None:
    with pytest.raises(ValueError):
        await write_note("C:/repo", "x" * (MAX_NOTE_BYTES + 1), _runner())


async def test_ensure_push_config_and_init() -> None:
    runner = _runner({"config-add": "", "notes-add": ""})
    await ensure_push_config("C:/repo", runner)
    await init_note("C:/repo", "初始规范", runner)
    assert any("refs/notes/*" in a for call in runner.calls for a in call)
