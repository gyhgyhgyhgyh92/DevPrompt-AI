"""真实 LLM 冒烟：跑一次完整的 AGENTIC 循环端到端。

与 pytest 的区别：pytest 用 ScriptedDecider 断言编排逻辑，这里用真实模型验证
「决策层真的会选动作、模型真的会声明 claims、降档真的会触发」。

用法（会真实调用模型并产生费用）：
    uv run python scripts/smoke_real_llm.py \
        --project-root eval/recall/mock-react-admin \
        --sentence "把提交按钮改成主色"

多轮继承（同一 db + 同一 session_id，原句传空串即沿用上一轮目标）：
    uv run python scripts/smoke_real_llm.py --db-path ./.logs/smoke.db \
        --project-root eval/recall/mock-react-admin \
        --sentence "把提交按钮改成主色"
    uv run python scripts/smoke_real_llm.py --db-path ./.logs/smoke.db \
        --project-root eval/recall/mock-react-admin \
        --sentence "" --session-id <id>

退出码：0 = 到达 DONE；1 = 未到 DONE；2 = LLM 配置缺失。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

from devprompt_ai.config import AppConfig
from devprompt_ai.service import build_default


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实 LLM 的 agentic 冒烟")
    parser.add_argument("--project-root", required=True, help="目标项目根（真实目录）")
    parser.add_argument("--sentence", required=True, help="中文原句；空串 = 沿用上一轮")
    parser.add_argument("--session-id", default="", help="非空则在同一会话开新一轮")
    parser.add_argument(
        "--db-path",
        default="",
        help="空则用进程临时库；多轮冒烟必须显式指定同一路径",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    # 只放行结构化事件：冒烟要看 evidence.reused / stale_reprobe / hook.ran 这些事实
    events = logging.getLogger("devprompt.events")
    events.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[event] %(message)s"))
    events.addHandler(handler)

    db_path = args.db_path or str(Path(tempfile.gettempdir()) / "dpa-smoke.db")
    # 显式 db_path 优先于 .env 的 DB_PATH（init_settings 优先级最高），绝不污染真实会话库
    # `_env_file` 是 pydantic-settings BaseSettings 的构造参数，类型存根未收录 → 忽略该行
    cfg = AppConfig(_env_file=None, db_path=db_path)  # type: ignore[call-arg]
    problems = cfg.llm_problems()
    if problems:
        for name, purpose in problems:
            print(f"缺少 {name}：{purpose}")
        return 2

    print(f"provider={cfg.llm_provider or '（空）'} model={cfg.llm_model}")
    print(f"base_url={cfg.llm_base_url}")
    print(f"project_root={args.project_root}")
    print(f"db_path={db_path}\n")

    svc = await build_default(cfg)
    started = time.monotonic()
    snap = await svc.optimize(
        "local",
        args.project_root,
        args.sentence,
        request_id="smoke-real-1",
        session_id=args.session_id or None,
    )
    elapsed = time.monotonic() - started

    session = await svc._sessions.load(snap.session_id)  # noqa: SLF001
    data = session.data if session is not None else {}
    steps = data.get("agent_steps", [])
    facts = data.get("facts", [])

    print(f"状态      {snap.state} / {snap.status}    耗时 {elapsed:.1f}s")
    print(f"会话      {snap.session_id}")
    print(f"档位      {data.get('level')}    facts_complete={data.get('facts_complete')}")
    print(f"置信度    {data.get('probe_confidence')}（source={data.get('confidence_source')}）")
    print(f"检索      候选 {len(data.get('candidates', []))} 条")
    print(f"取证      {sum(1 for f in facts if f.get('passed'))}/{len(facts)} 项通过")
    print(f"方案      {len(snap.variants or [])} 套")
    print(f"agent     {len(steps)} 步")
    for step in steps:
        print(
            f"  #{step.get('index')} {step.get('action'):<9}"
            f" {step.get('outcome'):<9} {step.get('duration_ms')}ms"
        )

    report = data.get("claim_report") or {}
    if report:
        print(f"断言      {report.get('summary')}  coverage={report.get('coverage')}")
        for item in report.get("uncovered", [])[:3]:
            print(f"  未取证  {item}")

    unknowns = data.get("unknowns") or []
    if unknowns:
        print(f"待确认    {len(unknowns)} 项")
        for item in unknowns[:3]:
            guess = str(item.get("best_guess", ""))[:60]
            print(f"  - {item.get('ask')}  | 推断：{guess or '（无）'}")

    reused = data.get("facts_mtime_digest", "")
    if reused:
        print(f"指纹      {reused}")
    print(f"过期标记  {bool(data.get('evidence_stale'))}")
    answered = str(data.get("reply_text", ""))
    print(f"回答      {answered[:200] if answered else '（本轮无）'}")

    if snap.variants:
        first = snap.variants[0]
        print(f"\n首套标题  {first.title}")
        print(f"首套档位  {first.level}   claims {len(first.claims)} 条")
        print(f"正文前 200 字：\n{first.body[:200]}")

    return 0 if snap.state == "DONE" else 1


def main() -> int:
    return asyncio.run(_run(_parse()))


if __name__ == "__main__":
    raise SystemExit(main())
