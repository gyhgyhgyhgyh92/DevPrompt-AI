"""CLI 命令实现：驱动 ForgeService 并渲染快照。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from typing import Any

from rich.console import Console

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.interfaces.cli import prompts_flow, render
from devprompt_ai.service import FlowSnapshot, build_default

MASK = "******"


async def drive_optimize(
    console: Console,
    *,
    sentence: str,
    project: str,
    json_out: bool,
    session_id: str = "",
) -> None:
    cfg = AppConfig()
    cfg.validate()
    service = await build_default(cfg)
    try:
        if session_id:
            # --session 恢复：只读加载既有流程，进入交互循环（4H-8.1）
            snapshot = await service.resume("local", session_id, request_id=uuid.uuid4().hex)
        else:
            snapshot = await service.optimize(
                "local", project, sentence, request_id=uuid.uuid4().hex
            )
        await _interactive_loop(console, service, snapshot, json_out=json_out)
    except DevPromptError as exc:
        # 错误呈现规范（MUST-19 的 CLI 等价）：仅 code+message，不回传堆栈
        if json_out:
            print(json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"[red]错误 {exc.code}[/red]：{exc}")
        raise SystemExit(1) from exc
    except TimeoutError:  # py3.12 起 asyncio.TimeoutError 即内建 TimeoutError
        # LLM 调用超限（wait_for 触发）：同样不回传内部堆栈
        if json_out:
            print(json.dumps({"code": 5001, "message": "LLM 调用超时"}, ensure_ascii=False))
        else:
            console.print("[red]错误 5001[/red]：LLM 调用超时，请稍后重试或检查网络。")
        raise SystemExit(1) from None


async def _interactive_loop(
    console: Console, service: Any, snapshot: FlowSnapshot, *, json_out: bool
) -> None:
    while not json_out and snapshot.status in ("ask", "guardrail"):
        if snapshot.status == "guardrail":
            choice = prompts_flow.ask_guardrail(console, snapshot)
            snapshot = await service.guardrail_confirm(
                "local",
                snapshot.session_id,
                proceed=(choice == "continue"),
                request_id=uuid.uuid4().hex,
            )
        else:
            render.print_questions(console, snapshot)
            answers = prompts_flow.collect_answers(console, snapshot.questions)
            if answers.get("__escape__"):
                snapshot = await service.escape(
                    "local", snapshot.session_id, request_id=uuid.uuid4().hex
                )
            else:
                answers.pop("__escape__", None)
                snapshot = await service.ask_followup(
                    "local", snapshot.session_id, answers, request_id=uuid.uuid4().hex
                )
    if json_out:
        print(json.dumps(_payload(snapshot), ensure_ascii=False))
    else:
        render.print_result(console, snapshot)


def _payload(snapshot: FlowSnapshot) -> dict[str, Any]:
    # UnknownItem 是 slots dataclass 无 __dict__（偏差：计划的 q.__dict__ 会 AttributeError）
    return {
        "session_id": snapshot.session_id,
        "status": snapshot.status,
        "state": snapshot.state,
        "questions": [asdict(q) for q in snapshot.questions],
        "variant": snapshot.variant.model_dump() if snapshot.variant else None,
        "cleared": snapshot.cleared,
        "message": snapshot.message,
    }


async def print_config(console: Console, cfg: AppConfig) -> None:
    data = cfg.model_dump()
    # 偏差：计划掩码键含 mysql_password，v1.1 存储回改 SQLite 后 AppConfig 已无该字段
    for key in ("llm_api_key", "typesafe_api_key"):
        if data.get(key):
            data[key] = MASK
    for name, value in sorted(data.items()):
        console.print(f"{name} = {value}")


async def print_preference(console: Console, cfg: AppConfig, *, json_out: bool) -> None:
    # 偏差：计划在函数体内重新 import build_default，会绕过测试对模块属性的 monkeypatch，
    # 改用模块级导入（与 drive_optimize 同一绑定）
    service = await build_default(cfg)
    pref = await service.get_preference("local")
    if json_out:
        print(json.dumps(pref, ensure_ascii=False))
    else:
        for key, value in pref.items():
            console.print(f"{key} = {value}")


async def run_doctor(console: Console, cfg: AppConfig) -> None:
    from devprompt_ai.common.process import run_command

    console.print("[bold]DevPrompt AI · 环境自检[/bold]")
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "llm_config",
            bool(cfg.llm_base_url and cfg.llm_model),
            f"{cfg.llm_base_url} / {cfg.llm_model}",
        )
    )
    for tool in ("rg", "ctags", "git"):
        try:
            out = await run_command([tool, "--version"], timeout=5.0)
            checks.append((tool, True, out.splitlines()[0][:60]))
        except Exception as exc:  # 自检需捕获全部失败形态，逐项报告而非中断
            checks.append((tool, False, repr(exc)[:80]))
    try:
        from devprompt_ai.memory.session_store import SQLiteSessionStore

        store = SQLiteSessionStore(cfg.db_path)
        await store.init_schema()
        checks.append(("sqlite", True, cfg.db_path))
    except Exception as exc:  # 同上：SQLite 探针失败也要落到报告里
        checks.append(("sqlite", False, repr(exc)[:80]))
    for name, ok, detail in checks:
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"{mark} {name}: {detail}")


async def init_project(console: Console, project: str) -> None:
    from devprompt_ai.harness.process import LocalCommandRunner
    from devprompt_ai.memory.project_notes import ensure_push_config, init_note

    runner = LocalCommandRunner()
    spec = "DevPrompt AI 项目规范（由 devprompt init 生成初版，请编辑后运行 git notes 同步）。"
    await init_note(project, spec, runner)
    await ensure_push_config(project, runner)
    console.print(
        f"[green]已写入 L2 项目规范 note（refs/notes/devprompt）并配置推送：{project}[/green]"
    )
