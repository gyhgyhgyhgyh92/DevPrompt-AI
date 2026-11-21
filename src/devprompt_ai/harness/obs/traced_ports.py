"""Trace 包装器：在端口边界记录完整请求/响应（全量明文，密钥已掩码）。

包装器不改变原端口语义；采集器未启用或不在 turn 上下文时自动退化为直通。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from typing import Any, cast

from devprompt_ai.domain.decision.port import (
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.models import Candidate, FactResult
from devprompt_ai.domain.obs.contract.trace import (
    TraceKind,
    TraceStatus,
    hash_key,
    normalize_decision_args,
)
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader, StreamingCommandRunner


def _strip_route_keys(args: list[str]) -> list[str]:
    return [arg for arg in args if not arg.startswith("--route-key=")]


class TracedRunner:
    def __init__(self, inner: CommandRunner, collector: Any) -> None:
        self._inner = inner
        self._collector = collector

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        clean = _strip_route_keys(args)
        call_key = hash_key("tool", clean, cwd or "")
        started = time.monotonic()
        call_id = await self._collector.record(
            TraceKind.TOOL.value,
            "command",
            input={"args": clean, "cwd": cwd or "", "timeout": timeout},
            attributes={"call_key": call_key, "tool": clean[0] if clean else ""},
        )
        try:
            out = await self._inner.run(
                args, timeout=timeout, allowed_exit_codes=allowed_exit_codes, cwd=cwd
            )
        except Exception as exc:  # noqa: BLE001 - 记录失败后原样抛给调用方
            await self._collector.record(
                TraceKind.TOOL_RESULT.value,
                "command",
                output={"stderr": str(exc)},
                status=TraceStatus.FAILED.value,
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={
                    "call_key": call_key,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                parent_id=call_id,
            )
            raise
        await self._collector.record(
            TraceKind.TOOL_RESULT.value,
            "command",
            output={"stdout": out},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=call_id,
        )
        return out

    async def run_stream(
        self,
        args: list[str],
        *,
        on_line: Callable[[str], Awaitable[None]],
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        """流式变体（2026-11-15）：透传 inner 的 run_stream，**trace 仍只记最终态**。

        增量片段不写观测库——否则一次检索会把 trace 放大成百上千行事件。
        inner 不支持流式时抛 NotImplementedError，由上层回退到 run。
        """
        inner = self._inner
        if not isinstance(inner, StreamingCommandRunner):
            raise NotImplementedError("inner runner does not support streaming")
        clean = _strip_route_keys(args)
        call_key = hash_key("tool", clean, cwd or "")
        started = time.monotonic()
        call_id = await self._collector.record(
            TraceKind.TOOL.value,
            "command",
            input={"args": clean, "cwd": cwd or "", "timeout": timeout},
            attributes={"call_key": call_key, "tool": clean[0] if clean else ""},
        )
        try:
            out = await inner.run_stream(
                args,
                on_line=on_line,
                timeout=timeout,
                allowed_exit_codes=allowed_exit_codes,
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001 - 记录失败后原样抛给调用方
            await self._collector.record(
                TraceKind.TOOL_RESULT.value,
                "command",
                output={"stderr": str(exc)},
                status=TraceStatus.FAILED.value,
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={
                    "call_key": call_key,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                parent_id=call_id,
            )
            raise
        await self._collector.record(
            TraceKind.TOOL_RESULT.value,
            "command",
            output={"stdout": out},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=call_id,
        )
        return out


class TracedReader:
    def __init__(self, inner: FileReader, collector: Any) -> None:
        self._inner = inner
        self._collector = collector

    async def read(self, path: str) -> str:
        call_key = hash_key("file", path)
        started = time.monotonic()
        content = await self._inner.read(path)
        await self._collector.record(
            TraceKind.FILE.value,
            "read",
            input={"path": path},
            output={"content": content, "lines": content.count("\n") + 1},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "size_bytes": len(content.encode("utf-8", "ignore")),
            },
        )
        return content

    async def exists(self, path: str) -> bool:
        call_key = hash_key("file.exists", path)
        result = await self._inner.exists(path)
        await self._collector.record(
            TraceKind.FILE.value,
            "exists",
            input={"path": path},
            output={"exists": result},
            attributes={"call_key": call_key},
        )
        return result


class TracedGenerator:
    def __init__(self, inner: Any, collector: Any) -> None:
        self._inner = inner
        self._collector = collector

    async def generate_single(
        self, ctx: Any, locale: str = "zh-CN", *, fallback: bool = False
    ) -> Any:
        request = {"ctx": ctx.model_dump(), "locale": locale, "fallback": fallback}
        call_key = hash_key("llm", "generate_single", request)
        started = time.monotonic()
        before_tokens = _usage_total()
        request_id = await self._collector.record(
            TraceKind.LLM.value,
            "generate_single",
            input=request,
            attributes={
                "call_key": call_key,
                "purpose": "generate",
            },
        )
        try:
            draft = await self._inner.generate_single(ctx, locale, fallback=fallback)
        except Exception as exc:  # noqa: BLE001 - 记录失败后原样抛给调用方
            await self._collector.record(
                TraceKind.LLM_RESULT.value,
                "generate_single",
                status=TraceStatus.FAILED.value,
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={
                    "call_key": call_key,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "tokens": _tokens(before_tokens),
                },
                parent_id=request_id,
            )
            raise
        await self._collector.record(
            TraceKind.LLM_RESULT.value,
            "generate_single",
            output={"draft": draft.model_dump()},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "tokens": _tokens(before_tokens),
            },
            parent_id=request_id,
        )
        return draft

    async def answer(self, ctx: Any, locale: str = "zh-CN") -> str:
        request = {"ctx": ctx.model_dump(), "locale": locale}
        call_key = hash_key("llm", "answer", request)
        started = time.monotonic()
        before_tokens = _usage_total()
        request_id = await self._collector.record(
            TraceKind.LLM.value,
            "answer",
            input=request,
            attributes={
                "call_key": call_key,
                "purpose": "reply",
            },
        )
        try:
            text = str(await self._inner.answer(ctx, locale))
        except Exception as exc:  # noqa: BLE001 - 记录失败后原样抛给调用方
            await self._collector.record(
                TraceKind.LLM_RESULT.value,
                "answer",
                status=TraceStatus.FAILED.value,
                error={"type": type(exc).__name__, "message": str(exc)},
                attributes={
                    "call_key": call_key,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "tokens": _tokens(before_tokens),
                },
                parent_id=request_id,
            )
            raise
        await self._collector.record(
            TraceKind.LLM_RESULT.value,
            "answer",
            output={"text": text},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "tokens": _tokens(before_tokens),
            },
            parent_id=request_id,
        )
        return text


class TracedDecider:
    """包装 DecisionPort + ActionPlanner：记录完整入参与模型输出。"""

    def __init__(self, inner: Any, collector: Any) -> None:
        self._inner = inner
        self._collector = collector

    async def _call(self, method: str, args: dict[str, Any], call: Any) -> Any:
        call_key = hash_key("decision", method, args)
        started = time.monotonic()
        before_tokens = _usage_total()
        request_id = await self._collector.record(
            TraceKind.DECISION.value, method, input=args, attributes={"call_key": call_key}
        )
        result = await call()
        await self._collector.record(
            TraceKind.DECISION_RESULT.value,
            method,
            output={"result": result.model_dump()},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "tokens": _tokens(before_tokens),
            },
            parent_id=request_id,
        )
        return result

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        args = {"sentence": sentence, "candidates": [asdict(item) for item in candidates]}
        return cast(
            RankComponentsOutput,
            await self._call(
                "rank_components", args, lambda: self._inner.rank_components(sentence, candidates)
            ),
        )

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        args = {
            "sentence": sentence,
            "facts": [asdict(item) for item in facts],
            "answered": dict(answered or {}),
        }
        return cast(
            FactProbeOutput,
            await self._call(
                "probe_facts",
                args,
                lambda: self._inner.probe_facts(sentence, facts, answered=answered),
            ),
        )

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        args = {"context": context, "variants": variants}
        return cast(
            ScorePromptsOutput,
            await self._call(
                "score_prompts", args, lambda: self._inner.score_prompts(context, variants)
            ),
        )

    async def rewrite_query(self, sentence: str, previous_target: str = "") -> Any:
        """转发结构化改写（2026-11-19）：走同一 _call，Trace 上可见这次 LLM 调用。"""
        return await self._call(
            "rewrite_query",
            {"sentence": sentence, "previous_target": previous_target},
            lambda: self._inner.rewrite_query(sentence, previous_target),
        )

    async def next_action(self, **kwargs: Any) -> Any:
        # 决策入参先归一化：步骤耗时等抖动字段不参与 call_key（保证可回放）
        return await self._call(
            "next_action",
            normalize_decision_args(kwargs),
            lambda: self._inner.next_action(**kwargs),
        )


class TracedSymbolProvider:
    def __init__(self, inner: Any, collector: Any) -> None:
        self._inner = inner
        self._collector = collector

    async def get(self, root: str) -> Any:
        call_key = hash_key("symbols", root)
        started = time.monotonic()
        result = await self._inner.get(root)
        await self._collector.record(
            TraceKind.SYMBOLS.value,
            "symbol_table",
            input={"root": root},
            output={
                "symbols": [asdict(item) for item in result.symbols],
                "cache_hit": result.cache_hit,
                "cache_key": result.cache_key,
            },
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return result


def _usage_total() -> int:
    """当前请求已累计的 token 总数（只读，用于计算单次调用差值）。"""
    try:
        from devprompt_ai.common.cost import peek_llm_usage

        return int(peek_llm_usage().total)
    except Exception:  # noqa: BLE001 - 采集增强项，失败按 0
        return 0


def _tokens(before_total: int = 0) -> int:
    """单次 LLM 调用的 token 数：优先请求级聚合差值，回退最近一次调用。"""
    try:
        from devprompt_ai.common.cost import peek_llm_usage

        delta = int(peek_llm_usage().total) - before_total
        if delta > 0:
            return delta
    except Exception:  # noqa: BLE001 - 聚合不可用时走回退
        pass
    try:
        from devprompt_ai.harness.llm import last_usage

        usage = last_usage() or {}
        return int(usage.get("total_tokens") or 0)
    except Exception:  # noqa: BLE001 - 采集增强项，失败按 0
        return 0
