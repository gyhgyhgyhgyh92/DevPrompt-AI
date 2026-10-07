"""F-602 反问交互：批量问答、逃生口、护栏裁决面板。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from devprompt_ai.domain.decision.followup import UnknownItem
from devprompt_ai.service import FlowSnapshot

ESCAPE = "!"


def collect_answers(console: Console, questions: list[UnknownItem]) -> dict[str, str]:
    """收集批量答复；任一轮输入 ! 即逃生（MUST-26 ②）。空回车 = 跳过（采用推断）。"""
    console.print("[bold]请逐项回答（回车=采用推断；输入 [yellow]![/yellow] = 直接生成）[/bold]")
    answers: dict[str, str] = {}
    for q in questions:
        value = console.input(f"  {q.key} > ").strip()
        if value == ESCAPE:
            return {"__escape__": "1"}
        if value:
            answers[q.key] = value
    return answers


def ask_guardrail(console: Console, snapshot: FlowSnapshot) -> str:
    """MUST-26 ③：软护栏裁决面板。返回 continue / generate。"""
    cleared = ", ".join(snapshot.cleared) or "（无）"
    console.print(
        Panel.fit(
            f"已追问多轮。已澄清：{cleared}\n"
            "请选择：[bold]c[/bold] = 继续追问（清零护栏）｜[bold]g[/bold] = 直接生成",
            title="软护栏",
            border_style="yellow",
        )
    )
    while True:
        choice = console.input("  c/g > ").strip().lower()
        if choice in ("c", "g"):
            return "continue" if choice == "c" else "generate"
