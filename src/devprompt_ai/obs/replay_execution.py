"""Replay 执行适配器：用录制端口 + 内存存储 dry-run 复现一轮执行。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.models import FlowSession
from devprompt_ai.domain.obs.contract.trace import TraceEvent, TraceKind, to_plain
from devprompt_ai.domain.obs.replay.playback import Playback
from devprompt_ai.harness.obs.recorded_ports import (
    MissingRecordError,
    RecordedDecider,
    RecordedGenerator,
    RecordedReader,
    RecordedRunner,
    RecordedSymbolProvider,
)
from devprompt_ai.obs.memory_stores import MemorySessionStore, MemoryTurnStore


class ReplayExecutionAdapter:
    """实现 ``ReplayExecutionPort``：不调用真实 LLM/工具，不写真实 DB。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def execute(
        self,
        trace_events: Sequence[TraceEvent],
        *,
        collector: Any,
    ) -> dict[str, Any]:
        start = next(
            (event for event in trace_events if event.kind == TraceKind.TURN_START.value), None
        )
        if start is None:
            raise ValueError("Trace 缺少 turn.start，无法回放")
        seed = start.input.get("session_data")
        if not isinstance(seed, dict) or not seed:
            raise ValueError("Trace 未记录会话快照（旧版本 Trace），无法回放")
        sentence = str(start.input.get("sentence", ""))
        project_root = str(start.input.get("project_root", ""))
        if not sentence or not project_root:
            raise ValueError("Trace 缺少原句或项目路径，无法回放")

        playback = Playback.from_events(trace_events)
        sessions = MemorySessionStore()
        turns = MemoryTurnStore()
        session_id = f"replay-{uuid.uuid4().hex}"
        sessions.items[session_id] = FlowSession(
            session_id=session_id,
            user_id="local",
            state="DONE",
            data=dict(seed),
        )
        cfg = self._cfg.model_copy(
            update={
                "obs_trace_enabled": False,
                "obs_metrics_enabled": False,
                "obs_replay_enabled": False,
            }
        )
        # 延迟导入：避免 obs 包与 service 的模块级循环依赖
        from devprompt_ai.service import ForgeService, reset_run_cache

        # 运行期缓存必须清空：命中缓存会跳过决策调用，导致节点流与录制不一致
        reset_run_cache()

        service = ForgeService(
            cfg=cfg,
            decider=cast(Any, RecordedDecider(playback, collector)),
            sessions=sessions,
            runner=RecordedRunner(playback, collector),
            reader=RecordedReader(playback, collector),
            generator=RecordedGenerator(playback, collector),
            symbols_provider=cast(Any, RecordedSymbolProvider(playback, collector)),
            turns=turns,
            trace=collector,
        )
        snapshot = await service.optimize(
            "local",
            project_root,
            sentence,
            request_id="replay",
            session_id=session_id,
        )
        if playback.missing:
            raise MissingRecordError("playback", ",".join(playback.missing[:3]))
        return cast(dict[str, Any], to_plain(snapshot))
