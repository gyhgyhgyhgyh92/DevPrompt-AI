"""运行时装配：把存储、总线、会话池与运行管理器组装成单例。

放在 runtime 层而不是 interfaces：表现层不得直接 import `memory/`（MUST-06）。
快照序列化由调用方注入，避免 runtime 反向依赖 interfaces。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.memory.intervention_store import SQLiteInterventionStore
from devprompt_ai.memory.run_store import SQLiteRunStore
from devprompt_ai.memory.startup_safety_check import abort_orphans_after_lock_takeover
from devprompt_ai.runtime.events import EventBus
from devprompt_ai.runtime.interventions import InterventionBroker
from devprompt_ai.runtime.lock import SingleWriterLock, acquire_writer_lock, release_writer_lock
from devprompt_ai.runtime.runs import RunManager, SnapshotSerializer
from devprompt_ai.runtime.sessions import SessionPool
from devprompt_ai.service import ForgeService


@dataclass
class RuntimeBundle:
    service: ForgeService
    events: SQLiteEventStore
    runs: SQLiteRunStore
    bus: EventBus
    pool: SessionPool
    manager: RunManager
    interventions: InterventionBroker
    lock: SingleWriterLock


_runtime: RuntimeBundle | None = None


async def get_runtime(service: ForgeService, serialize: SnapshotSerializer) -> RuntimeBundle:
    """懒加载单例；复用同一条 service 与同一个 SQLite 文件。"""
    global _runtime
    if _runtime is None:
        db_path = service.config.db_path
        # 先拿写锁再开库：失败时不留半初始化状态（fail-closed）。
        lock = acquire_writer_lock(
            db_path,
            enabled=service.config.single_writer_lock,
            stale_after_s=service.config.writer_lock_stale_seconds,
        )
        try:
            events = SQLiteEventStore(db_path)
            await events.init_schema()
            # H5 启动校验：篡改/截断的事件行在此暴露（只告警，不阻断启动）。
            await events.verify_checksums()
            runs = SQLiteRunStore(db_path)
            await runs.init_schema()
            # H1 崩溃恢复：写锁成功意味着旧持有者确认死亡，立即收尾全部遗留 run 与
            # 活跃 turn/session；否则新 run 会被 start_turn 以 6001 拒绝，前端卡死
            # 在「进行中」直到 30 分钟兜底阈值生效。锁未启用时退回保守 30 分钟。
            stale_minutes = 0 if lock.acquired else 30
            await runs.mark_orphans_aborted(stale_minutes)
            if lock.acquired:
                abort_orphans_after_lock_takeover(db_path)
            bus = EventBus(events)
            pool = SessionPool()

            # 阶段7 周期 checkpoint：service 每 5 步经此把进度落 run_events（执行体不依赖订阅）。
            async def _checkpoint(session_id: str, payload: dict[str, Any]) -> None:
                await bus.append(session_id, "agent.checkpoint", payload)
                # 断点续跑（2026-11-19）：同一 run 的最新全量快照落表，一次 get 即可恢复。
                # 旁路失败只降级，不影响主循环。
                try:
                    current = await runs.latest_for_session(session_id)
                    if current is not None and current.status == "running":
                        await runs.save_snapshot(current.run_id, payload)
                except Exception:  # noqa: BLE001 - checkpoint 是旁路
                    logger.debug("checkpoint.snapshot_failed", exc_info=True)

            service.checkpoint_sink = _checkpoint
            manager = RunManager(
                service=service,
                bus=bus,
                runs=runs,
                pool=pool,
                serialize=serialize,
            )
            _runtime = RuntimeBundle(
                service=service,
                events=events,
                runs=runs,
                bus=bus,
                pool=pool,
                manager=manager,
                interventions=InterventionBroker(SQLiteInterventionStore(db_path), bus),
                lock=lock,
            )
        except BaseException:
            release_writer_lock(lock)
            raise
    return _runtime


def reset_runtime() -> None:
    """测试用：释放写锁并丢弃单例（不影响已运行的执行体）。"""
    global _runtime
    if _runtime is not None:
        release_writer_lock(_runtime.lock)
    _runtime = None
