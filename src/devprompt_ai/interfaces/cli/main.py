"""F-601 CLI 命令（Typer）。业务全部经 ForgeService（MUST-10），本层零业务判定。"""

from __future__ import annotations

import typer
from rich.console import Console

from devprompt_ai.config import AppConfig

app = typer.Typer(help="DevPrompt AI — 把模糊需求编译为工程级提示词")
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """进入交互式优化（默认命令）。"""
    if ctx.invoked_subcommand is None:
        sentence = typer.prompt("请描述你的需求")
        _run_optimize(sentence=sentence, project=".", json_out=False, no_color=False)


@app.command()
def optimize(
    sentence: str,
    project: str = typer.Option(".", "--project", help="目标项目根目录"),
    json_out: bool = typer.Option(False, "--json", help="以 JSON 输出快照"),
    no_color: bool = typer.Option(False, "--no-color", help="禁用彩色输出"),
) -> None:
    """单次优化：检索 → 探针 → 反问（可逃生）→ 生成。"""
    _run_optimize(sentence=sentence, project=project, json_out=json_out, no_color=no_color)


def _run_optimize(*, sentence: str, project: str, json_out: bool, no_color: bool) -> None:
    import asyncio

    from devprompt_ai.interfaces.cli import commands

    cmd_console = Console(no_color=no_color)
    asyncio.run(
        commands.drive_optimize(cmd_console, sentence=sentence, project=project, json_out=json_out)
    )


@app.command()
def web() -> None:
    """启动 Web 服务（阶段六交付）。"""
    console.print("Web 形态在阶段六交付（真源 T6-1）；当前请使用 [bold]optimize[/bold] 命令。")


@app.command()
def config() -> None:
    """查看配置（密钥脱敏）。"""
    import asyncio

    from devprompt_ai.interfaces.cli import commands

    asyncio.run(commands.print_config(Console(), AppConfig(_env_file=None)))  # type: ignore[call-arg]


@app.command()
def preference(json_out: bool = typer.Option(False, "--json")) -> None:
    """查看偏好向量（L3 阶段五接入，当前为初始值）。"""
    import asyncio

    from devprompt_ai.interfaces.cli import commands

    asyncio.run(
        commands.print_preference(Console(), AppConfig(_env_file=None), json_out=json_out)  # type: ignore[call-arg]
    )


@app.command()
def doctor() -> None:
    """环境自检：python/rg/ctags/git/SQLite/LLM 配置。"""
    import asyncio

    from devprompt_ai.interfaces.cli import commands

    asyncio.run(commands.run_doctor(Console(), AppConfig(_env_file=None)))  # type: ignore[call-arg]


@app.command()
def init(project: str = typer.Option(".", "--project")) -> None:
    """初始化项目规范（写入 L2 Git notes，要求目标目录为 git 仓库且有 commit）。"""
    import asyncio

    from devprompt_ai.interfaces.cli import commands

    asyncio.run(commands.init_project(Console(), project))
