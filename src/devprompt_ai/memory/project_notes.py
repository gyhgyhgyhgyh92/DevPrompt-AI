"""F-502 L2 项目记忆：Git notes（key=devprompt，单条 ≤8KB 纯文本）。"""

from __future__ import annotations

from devprompt_ai.domain.retrieval.ports import CommandRunner

NOTE_REF = "devprompt"
MAX_NOTE_BYTES = 8192
_GIT_OK = frozenset({0, 1})  # 1 = notes list 为空等


def _git(root: str, *args: str, route_key: str = "") -> list[str]:
    args_list = ["git", "-C", root, *args]
    if route_key:
        # 测试路由键约定：LocalCommandRunner/测试 Fake 过滤 --route-key
        args_list.append(f"--route-key={route_key}")
    return args_list


async def write_note(root: str, content: str, runner: CommandRunner) -> None:
    """写项目规范 note（覆盖式 add -f）。超 8KB 拒绝（F-502 行为列）。"""
    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        raise ValueError(f"L2 note 超过 {MAX_NOTE_BYTES} 字节上限")
    await runner.run(
        _git(
            root,
            "notes",
            "--ref",
            NOTE_REF,
            "add",
            "-f",
            "-m",
            content,
            "HEAD",
            route_key="notes-add",
        )
    )


async def read_notes(root: str, runner: CommandRunner) -> list[tuple[str, str]]:
    """返回 [(对象哈希, note 内容)]；无 notes 返回空列表。"""
    listing = await runner.run(
        _git(root, "notes", "--ref", NOTE_REF, "list", route_key="notes-list"),
        allowed_exit_codes=_GIT_OK,
    )
    notes: list[tuple[str, str]] = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        obj = parts[0]
        content = await runner.run(
            _git(root, "notes", "--ref", NOTE_REF, "show", obj, route_key="notes-show"),
            allowed_exit_codes=_GIT_OK,
        )
        notes.append((obj, content))
    return notes


async def ensure_push_config(root: str, runner: CommandRunner) -> None:
    """F-502：推送配置使 notes 随远端同步（幂等 --add）。"""
    await runner.run(
        _git(root, "config", "--add", "remote.origin.push", "refs/notes/*", route_key="config-add")
    )


async def refresh_notes(root: str, runner: CommandRunner) -> None:
    """手动刷新入口：拉取远端 notes（无远端时 ProcessError 上抛由调用方提示）。"""
    await runner.run(_git(root, "fetch", "origin", "refs/notes/*:refs/notes/*", route_key="fetch"))


async def init_note(root: str, spec_text: str, runner: CommandRunner) -> None:
    """F-601 init：写入初始项目规范 note（要求 root 已有 commit）。"""
    await write_note(root, spec_text, runner)
