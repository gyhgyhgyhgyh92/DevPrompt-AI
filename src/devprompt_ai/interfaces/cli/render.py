"""Rich 渲染：快照 → 终端输出。零业务判定（MUST-08/10）。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from devprompt_ai.service import FlowSnapshot


def print_questions(console: Console, snapshot: FlowSnapshot) -> None:
    console.print(
        Panel.fit(
            f"[bold]需要澄清 {len(snapshot.questions)} 项[/bold]"
            "（直接回车 = 采用推断；输入 [yellow]![/yellow] = 直接生成）",
            border_style="cyan",
        )
    )
    for q in snapshot.questions:
        console.print(f"[cyan]{q.key}[/cyan] {q.ask}")
        console.print(f"  [dim]推断：{q.best_guess or '无'}｜原因：{q.reason}[/dim]")


def print_result(console: Console, snapshot: FlowSnapshot) -> None:
    if snapshot.variant is None:
        console.print("[red]未生成方案[/red]")
        return
    console.print(
        Panel(
            f"[bold]{snapshot.variant.title}[/bold]（档位 {snapshot.variant.level}）\n\n"
            f"{snapshot.variant.body}\n\n" + "\n".join(f"- {c}" for c in snapshot.variant.changes),
            title="优化结果",
            border_style="green",
        )
    )
