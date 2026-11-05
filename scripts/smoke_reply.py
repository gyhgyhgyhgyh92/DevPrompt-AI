"""真实 LLM 验证 reply 动作（2026-11-05）。

为什么不走完整 optimize：首轮取证常常不足（实测 4/7），会停在 ASKING，
拿不到「已有方案」这个前置条件——而 reply 恰恰只在有方案时才有意义。
这里手工构造该前置条件（方案正文 + 取证 + 指纹），其余全部走真实链路：
真实 SymbolTableProvider 算指纹、真实 LLMGenerator 调模型、真实 _finish_turn 落库。

用法：
    uv run python scripts/smoke_reply.py \
        --project-root eval/recall/mock-react-admin \
        --question "为什么选 B 档？它和 C 档的差异在哪？"

退出码：0 = 拿到回答；1 = 回答为空；2 = LLM 配置缺失。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from devprompt_ai.config import AppConfig
from devprompt_ai.service import build_default
from devprompt_ai.state import FlowState, hop, start_turn

#: 构造的上一轮方案（模拟「用户已经看过三套方案」的状态）
_SEED_VARIANTS = [
    {
        "title": "最小改动：只换颜色变量",
        "body": "把 SubmitButton 的背景改成 var(--color-primary-500)，不动结构。",
        "changes": ["src/components.tsx 换背景色"],
        "level": "B",
        "claims": [],
    },
    {
        "title": "完整方案：颜色 + 加载态 + 无障碍",
        "body": "同时补 loading 分支、aria-busy 与 disabled 联动。",
        "changes": ["src/components.tsx 增加 loading 分支"],
        "level": "C",
        "claims": [],
    },
]

#: 构造的取证结果（真实项目里来自 verify_facts，这里固定为「文件与符号存在」）
_SEED_FACTS = [
    {"key": "target_file_exists", "passed": True, "evidence": "file=src/components.tsx"},
    {"key": "symbol_in_file", "passed": True, "evidence": "src/components.tsx:12:SubmitButton"},
    {"key": "token_defined", "passed": False, "evidence": "未找到"},
]


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实 LLM 的 reply 冒烟")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--question", required=True, help="讨论性追问")
    parser.add_argument("--db-path", default="")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    # Windows 控制台默认 GBK：模型回答会带 U+2212（−）之类的字符，
    # 不切换编码会让「回答已生成」变成「打印时崩溃」。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    events = logging.getLogger("devprompt.events")
    events.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[event] %(message)s"))
    events.addHandler(handler)

    db_path = args.db_path or str(Path(tempfile.gettempdir()) / "dpa-smoke-reply.db")
    cfg = AppConfig(_env_file=None, db_path=db_path)  # type: ignore[call-arg]
    problems = cfg.llm_problems()
    if problems:
        for name, purpose in problems:
            print(f"缺少 {name}：{purpose}")
        return 2

    print(f"model={cfg.llm_model}  base={cfg.llm_base_url}")
    print(f"question={args.question}\n")

    svc = await build_default(cfg)
    # 真实指纹：与 _check_evidence_freshness 用同一来源，避免误报过期
    table = await svc._symbols_provider.get(args.project_root)  # noqa: SLF001
    session = await start_turn(svc._sessions, "local", None)  # noqa: SLF001
    session.data = {
        "sentence": args.question,
        "project_root": args.project_root,
        "last_request_id": "smoke-reply",
        "clarifications": {},
        "cost_tokens": 0,
        "turn_memory": {
            "sentence": "把提交按钮改成主色并补上加载态",
            "variants": _SEED_VARIANTS,
            "facts": _SEED_FACTS,
            "facts_mtime_digest": table.cache_key,
            "clarifications": {},
        },
        "facts": _SEED_FACTS,
        "facts_mtime_digest": table.cache_key,
        "target": {"name": "SubmitButton", "path": "src/components.tsx", "line": 12},
        # 推荐判定：回答「为什么选 B」的唯一依据来源（2026-11-05）
        "ranking": {
            "variant": "B",
            "gap": 0.21,
            "confidence": 0.74,
            "marked": True,
            "reason": "B 档适配度最高，且与次优差距超过硬阈值",
            "fit": 0.82,
            "total": 0.79,
        },
        # 逐档明细：回答「C 差多少、为什么落选」需要它（2026-11-05）
        "ranking_details": {
            "B": {"fit": 0.82, "total": 0.79},
            "C": {"fit": 0.61, "total": 0.61},
        },
    }
    await hop(session, FlowState.AGENTIC, svc._sessions)  # noqa: SLF001
    await svc._begin_turn(session)  # noqa: SLF001

    snap = await svc._act_reply(session)  # noqa: SLF001

    print(f"状态      {snap.state} / {snap.status}")
    print(f"过期标记  {snap.evidence_stale}")
    print(f"方案数    {len(snap.variants)}")
    print(f"\n回答正文：\n{snap.reply_text or '（空）'}\n")

    return 0 if snap.reply_text.strip() else 1


def main() -> int:
    return asyncio.run(_run(_parse()))


if __name__ == "__main__":
    raise SystemExit(main())
