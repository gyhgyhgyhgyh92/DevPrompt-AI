"""Replay 录制端口：按 call_key 从 Trace 取原始输出，绝不真实调用 LLM/工具。"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, cast

from devprompt_ai.domain.decision.port import (
    FactProbeOutput,
    NextActionOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
)
from devprompt_ai.domain.generate.ports import ReplyOutput, VariantDraft
from devprompt_ai.domain.models import Symbol
from devprompt_ai.domain.obs.contract.trace import (
    TraceKind,
    TraceStatus,
    hash_key,
    normalize_decision_args,
)
from devprompt_ai.domain.obs.replay.playback import Playback
from devprompt_ai.harness.process import SymbolTableResult


class MissingRecordError(RuntimeError):
    def __init__(self, kind: str, call_key: str) -> None:
        super().__init__(f"录制缺失：{kind}:{call_key}")
        self.kind = kind
        self.call_key = call_key


def _strip_route_keys(args: list[str]) -> list[str]:
    return [arg for arg in args if not arg.startswith("--route-key=")]


class RecordedRunner:
    def __init__(self, playback: Playback, collector: Any) -> None:
        self._playback = playback
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
        record = self._playback.take(TraceKind.TOOL_RESULT.value, call_key)
        started = time.monotonic()
        call_id = await self._collector.record(
            TraceKind.TOOL.value,
            "command",
            input={"args": clean, "cwd": cwd or "", "timeout": timeout},
            attributes={"call_key": call_key},
        )
        if record is None:
            raise MissingRecordError("tool", call_key)
        out = str(record.output.get("stdout", ""))
        status = "ok"
        await self._collector.record(
            TraceKind.TOOL_RESULT.value,
            "command",
            output={"stdout": out},
            status=status,
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=call_id,
        )
        return out

    async def exists(self, path: str) -> bool:
        call_key = hash_key("file.exists", path)
        record = self._playback.take(TraceKind.FILE.value, call_key)
        if record is None:
            raise MissingRecordError("file.exists", call_key)
        result = bool(record.output.get("exists", False))
        await self._collector.record(
            TraceKind.FILE.value,
            "exists",
            input={"path": path},
            output={"exists": result},
            attributes={"call_key": call_key},
        )
        return result


class RecordedReader:
    def __init__(self, playback: Playback, collector: Any) -> None:
        self._playback = playback
        self._collector = collector

    async def read(self, path: str) -> str:
        call_key = hash_key("file", path)
        record = self._playback.take(TraceKind.FILE.value, call_key)
        started = time.monotonic()
        if record is None:
            raise MissingRecordError("file", call_key)
        content = str(record.output.get("content", ""))
        await self._collector.record(
            TraceKind.FILE.value,
            "read",
            input={"path": path},
            output={"content": content, "lines": content.count("\n") + 1},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return content

    async def exists(self, path: str) -> bool:
        call_key = hash_key("file.exists", path)
        record = self._playback.take(TraceKind.FILE.value, call_key)
        if record is None:
            raise MissingRecordError("file.exists", call_key)
        result = bool(record.output.get("exists", False))
        await self._collector.record(
            TraceKind.FILE.value,
            "exists",
            input={"path": path},
            output={"exists": result},
            attributes={"call_key": call_key},
        )
        return result


class RecordedGenerator:
    def __init__(self, playback: Playback, collector: Any) -> None:
        self._playback = playback
        self._collector = collector

    async def generate_single(
        self, ctx: Any, locale: str = "zh-CN", *, fallback: bool = False
    ) -> VariantDraft:
        request = {"ctx": ctx.model_dump(), "locale": locale, "fallback": fallback}
        call_key = hash_key("llm", "generate_single", request)
        record = self._playback.take(TraceKind.LLM_RESULT.value, call_key)
        started = time.monotonic()
        request_id = await self._collector.record(
            TraceKind.LLM.value, "generate_single", input=request, attributes={"call_key": call_key}
        )
        if record is None:
            raise MissingRecordError("llm", call_key)
        draft = VariantDraft(**record.output.get("draft", {}))
        await self._collector.record(
            TraceKind.LLM_RESULT.value,
            "generate_single",
            output={"draft": draft.model_dump()},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=request_id,
        )
        return draft

    async def answer(self, ctx: Any, locale: str = "zh-CN") -> str:
        request = {"ctx": ctx.model_dump(), "locale": locale}
        call_key = hash_key("llm", "answer", request)
        record = self._playback.take(TraceKind.LLM_RESULT.value, call_key)
        started = time.monotonic()
        request_id = await self._collector.record(
            TraceKind.LLM.value, "answer", input=request, attributes={"call_key": call_key}
        )
        if record is None:
            raise MissingRecordError("llm", call_key)
        text = str(record.output.get("text", ""))
        await self._collector.record(
            TraceKind.LLM_RESULT.value,
            "answer",
            output={"text": text},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=request_id,
        )
        return text


class RecordedDecider:
    def __init__(self, playback: Playback, collector: Any) -> None:
        self._playback = playback
        self._collector = collector

    async def _call(self, method: str, args: dict[str, Any], model: type[Any]) -> Any:
        call_key = hash_key("decision", method, args)
        record = self._playback.take(TraceKind.DECISION_RESULT.value, call_key)
        started = time.monotonic()
        request_id = await self._collector.record(
            TraceKind.DECISION.value, method, input=args, attributes={"call_key": call_key}
        )
        if record is None:
            raise MissingRecordError("decision", call_key)
        result = model(**record.output.get("result", {}))
        await self._collector.record(
            TraceKind.DECISION_RESULT.value,
            method,
            output={"result": result.model_dump()},
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            parent_id=request_id,
        )
        return result

    async def rank_components(self, sentence: str, candidates: list[Any]) -> RankComponentsOutput:
        args = {"sentence": sentence, "candidates": [asdict(item) for item in candidates]}
        return cast(
            RankComponentsOutput,
            await self._call("rank_components", args, RankComponentsOutput),
        )

    async def probe_facts(
        self, sentence: str, facts: list[Any], *, answered: dict[str, str] | None = None
    ) -> FactProbeOutput:
        args = {
            "sentence": sentence,
            "facts": [asdict(item) for item in facts],
            "answered": answered or {},
        }
        return cast(FactProbeOutput, await self._call("probe_facts", args, FactProbeOutput))

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        args = {"context": context, "variants": variants}
        return cast(
            ScorePromptsOutput,
            await self._call("score_prompts", args, ScorePromptsOutput),
        )

    async def next_action(self, **kwargs: Any) -> NextActionOutput:
        return cast(
            NextActionOutput,
            await self._call("next_action", normalize_decision_args(kwargs), NextActionOutput),
        )


class RecordedSymbolProvider:
    def __init__(self, playback: Playback, collector: Any) -> None:
        self._playback = playback
        self._collector = collector

    async def get(self, root: str) -> SymbolTableResult:
        call_key = hash_key("symbols", root)
        record = self._playback.take(TraceKind.SYMBOLS.value, call_key)
        started = time.monotonic()
        if record is None:
            raise MissingRecordError("symbols", call_key)
        symbols = [Symbol(**item) for item in record.output.get("symbols", [])]
        result = SymbolTableResult(
            symbols=symbols,
            cache_hit=bool(record.output.get("cache_hit", False)),
            cache_key=str(record.output.get("cache_key", "")),
        )
        await self._collector.record(
            TraceKind.SYMBOLS.value,
            "symbol_table",
            input={"root": root},
            output={
                "symbols": [asdict(item) for item in symbols],
                "cache_hit": result.cache_hit,
                "cache_key": result.cache_key,
            },
            status=TraceStatus.OK.value,
            attributes={
                "call_key": call_key,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return result


__all__ = [
    "MissingRecordError",
    "RecordedDecider",
    "RecordedGenerator",
    "RecordedReader",
    "RecordedRunner",
    "RecordedSymbolProvider",
    "ReplyOutput",
]
