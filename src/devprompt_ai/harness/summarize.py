"""LLM 摘要（B11）：只在长会话压缩时调用，失败一律回退确定性 handoff。

摘要器不负责「要不要压」——那是 compactor 的职责；这里只做「压成什么」。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.context.summary import (
    build_summary_prompt,
    choose_summary,
    deterministic_handoff,
)
from devprompt_ai.harness.llm import chat_structured


class SummaryOutput(BaseModel):
    summary: str = ""


async def summarize_history(
    cfg: AppConfig,
    history: str,
    *,
    required_terms: Sequence[str] = (),
    previous: str = "",
    fallback_context: dict[str, object] | None = None,
) -> tuple[str, bool]:
    """返回 ``(摘要, 是否回退)``；任何异常都走兜底，不向上抛。"""
    system, user = build_summary_prompt(history, previous=previous)
    ctx = fallback_context or {}

    def _items(key: str) -> tuple[str, ...]:
        value = ctx.get(key, ())
        return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()

    fallback = deterministic_handoff(
        objective=str(ctx.get("objective", "")),
        decisions=_items("decisions"),
        files=_items("files"),
        errors=_items("errors"),
        current=str(ctx.get("current", "")),
    )
    try:
        out = await chat_structured(
            cfg,
            SummaryOutput,
            system,
            user,
            timeout=cfg.llm_generate_timeout,
            purpose="summarize",
        )
        return choose_summary(out.summary, required=required_terms, fallback=fallback)
    except Exception:  # noqa: BLE001 - 摘要失败必须降级，不能拖垮主流程
        return fallback, True
