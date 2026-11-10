"""模型参数全链路探针（2026-11-10）。

用途：验证「思考强度 / 上下文长度」是否真的进入模型调用层，而不是只存在设置里。

两种模式：

- 默认 **dry-run**：不联网，打印当前激活条目的实际参数与各 API 形态的请求形状；
- ``--live``：用同一句短 prompt 真实调用一次，打印耗时与 usage（不含 prompt/密钥）。

示例：

    uv run python scripts/probe_model_tuning.py
    uv run python scripts/probe_model_tuning.py --live --effort high
    uv run python scripts/probe_model_tuning.py --live --effort low --window 131072

注意：本脚本不进入 CI，不写日志文件；在线模式会产生真实 token 费用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.model.tuning import (
    anthropic_thinking,
    gemini_thinking_budget,
)
from devprompt_ai.harness.llm import chat_structured, last_usage


class _ProbeOutput(BaseModel):
    """最小结构化输出：只验证调用链，不验证业务语义。"""

    answer: str = ""


def _describe(cfg: AppConfig) -> dict[str, Any]:
    """当前激活条目的参数视图（不含密钥）。"""
    return {
        "provider": cfg.llm_provider,
        "model": cfg.llm_model,
        "api_mode": cfg.api_mode or "(provider default)",
        "reasoning_effort_raw": cfg.reasoning_effort_value(),
        "context_window_effective": cfg.runtime_window(),
        "max_context_length_field": cfg.max_context_length,
        "global_context_window_tokens": cfg.context_window_tokens,
        "extra_body": cfg.extra_body_params(),
        "effective_llm_params": cfg.effective_llm_params(),
    }


def _native_preview(cfg: AppConfig) -> dict[str, Any]:
    """原生适配器会构造出的 thinking 字段（仅预览，不联网）。"""
    effort = cfg.reasoning_effort_value()
    max_tokens = int(cfg.effective_llm_params().get("max_tokens") or 4096)
    return {
        "anthropic_thinking": anthropic_thinking(effort, max_tokens),
        "gemini_thinking_budget": gemini_thinking_budget(effort),
    }


async def _live_call(cfg: AppConfig) -> dict[str, Any]:
    """真实调用一次；只打印状态、耗时与 usage。"""
    started = time.monotonic()
    output = await chat_structured(
        cfg,
        _ProbeOutput,
        "你是连通性探针。只输出 JSON，不要解释。",
        '请输出 {"answer": "ok"}',
        timeout=cfg.llm_timeout,
        purpose="generate",
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "answer": output.answer,
        "elapsed_ms": elapsed_ms,
        "usage": last_usage(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="模型思考强度/上下文长度全链路探针")
    parser.add_argument(
        "--live",
        action="store_true",
        help="真实调用一次当前激活模型（会产生 token 费用）",
    )
    parser.add_argument(
        "--effort",
        default="",
        help="覆盖思考强度（如 none/low/medium/high/max）；空 = 使用当前设置",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=0,
        help="覆盖上下文窗口（token）；0 = 使用当前设置",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出，便于脚本消费",
    )
    return parser.parse_args()


def _with_overrides(cfg: AppConfig, *, effort: str, window: int) -> AppConfig:
    params = dict(cfg.llm_params or {})
    if effort:
        params["reasoning_effort"] = effort.strip().lower()
    updates: dict[str, Any] = {"llm_params": params}
    if window > 0:
        updates["max_context_length"] = window
    return cfg.model_copy(update=updates)


async def _run() -> int:
    args = _parse_args()
    cfg = _with_overrides(AppConfig(), effort=args.effort, window=args.window)
    report: dict[str, Any] = {
        "dry_run": _describe(cfg),
        "native_preview": _native_preview(cfg),
    }
    if args.live:
        try:
            report["live"] = await _live_call(cfg)
        except Exception as exc:  # noqa: BLE001 - 探针要打印失败原因而不是堆栈
            report["live_error"] = f"{type(exc).__name__}: {exc}"
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for section, value in report.items():
            print(f"[{section}]")
            if isinstance(value, dict):
                for key, item in value.items():
                    print(f"  {key}: {item}")
            else:
                print(f"  {value}")
    return 0 if "live_error" not in report else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
