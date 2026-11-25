"""Reflection 偏好采样批次（2026-11-24）。

用真实 LLM + 真实仓库跑 20 个会话，按三种策略回答澄清问题：
选项、采纳默认、自由输入。用于验证链路与生成指标基线，不代表真实用户行为。

隔离：
- DB_PATH=~/.devprompt-ai/reflection-batch.db
- LOG_DIR=./.logs-batch
- REFLECTION_AGENT_ID=devprompt-batch

运行：
    .\\.venv\\Scripts\\python.exe scripts/run_reflection_batch.py
    .\\.venv\\Scripts\\python.exe scripts/run_reflection_batch.py --control

`--control` 关闭 Reflection，用同一批句子与同一套回答策略跑对照。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

from devprompt_ai.config import AppConfig  # noqa: E402
from devprompt_ai.observability.logging import install_file_sink  # noqa: E402
from devprompt_ai.service import FlowSnapshot, build_default  # noqa: E402

CASES: tuple[str, ...] = (
    "把 Menu 按钮的键盘导航改得更顺手",
    "Dialog 关闭后把焦点还给触发按钮",
    "Listbox 选项多时加一个搜索框",
    "Combobox 输入没有匹配项时给空状态提示",
    "Switch 增加禁用态样式",
    "RadioGroup 支持方向键切换",
    "Tabs 支持手动激活模式",
    "Popover 点击外部关闭",
    "Disclosure 展开动画不要太突兀",
    "Transition 支持减少动态效果偏好",
    "Menu.Item 的 disabled 状态读屏要能识别",
    "Listbox 多选模式的选中态需要更明显",
    "Dialog 打开时锁定背景滚动",
    "Combobox 支持异步加载选项",
    "Switch 的 label 点击也能切换",
    "RadioGroup 支持自定义渲染选项",
    "Tabs 的选中项在 URL 里可恢复",
    "Popover 的箭头跟随锚点",
    "Disclosure 默认展开第一项",
    "Menu 的分组标题支持 sticky",
)
STRATEGIES = ("option", "best_guess", "free_text")
FREE_TEXT = "最小改动，不加依赖，只改前端"
MAX_ASK_ROUNDS = 3
ROOT = str(Path("eval/repos/headlessui").resolve())


def _answers(snap: FlowSnapshot, strategy: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for question in snap.questions:
        if strategy == "option" and question.options:
            out[question.key] = question.options[0].label
        elif strategy == "best_guess" and question.best_guess:
            out[question.key] = question.best_guess
        else:
            out[question.key] = FREE_TEXT
    return out


async def _run_case(svc: object, index: int, sentence: str) -> tuple[str, int]:
    snap = await svc.optimize(  # type: ignore[attr-defined]
        "local",
        ROOT,
        sentence,
        request_id=uuid.uuid4().hex,
        session_id=uuid.uuid4().hex,
        create_session=True,
    )
    asks = 0
    strategy = STRATEGIES[index % len(STRATEGIES)]
    while snap.status == "ask" and asks < MAX_ASK_ROUNDS:
        answers = _answers(snap, strategy)
        if not answers:
            break
        asks += 1
        snap = await svc.ask_followup(  # type: ignore[attr-defined]
            "local",
            snap.session_id,
            answers,
            request_id=uuid.uuid4().hex,
        )
    return snap.status, asks


def _configure(control: bool) -> None:
    """在 AppConfig() 之前注入隔离环境；对照组关闭 Reflection。"""
    os.environ["REFLECTION_ENABLED"] = "false" if control else "true"
    os.environ["REFLECTION_AGENT_ID"] = "devprompt-control" if control else "devprompt-batch"
    os.environ["DB_PATH"] = (
        "~/.devprompt-ai/reflection-control.db"
        if control
        else "~/.devprompt-ai/reflection-batch.db"
    )
    os.environ["LOG_DIR"] = "./.logs-control" if control else "./.logs-batch"


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=len(CASES))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--control", action="store_true", help="关闭 Reflection 跑同题对照")
    args = parser.parse_args(argv)
    _configure(args.control)
    cases = CASES[args.offset : args.offset + args.limit]
    cfg = AppConfig()
    cfg.validate()
    install_file_sink(cfg.log_dir)
    svc = await build_default(cfg)
    asked = 0
    failed = 0
    started = time.monotonic()
    for index, sentence in enumerate(cases, start=1):
        try:
            status, rounds = await _run_case(svc, args.offset + index - 1, sentence)
        except Exception as exc:  # noqa: BLE001 - 批次单条失败不拖垮其余
            failed += 1
            print(f"[{index}/{len(cases)}] failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        if rounds > 0:
            asked += 1
        print(f"[{index}/{len(cases)}] status={status} ask_rounds={rounds}", flush=True)
    elapsed = time.monotonic() - started
    print(
        f"done: total={len(cases)} asked={asked} failed={failed}"
        f" elapsed={elapsed:.1f}s db={cfg.db_path} log_dir={cfg.log_dir}",
        flush=True,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
