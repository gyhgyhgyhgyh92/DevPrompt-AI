"""运行时装配：把存储、总线、会话池与运行管理器组装成单例。

放在 runtime 层而不是 interfaces：表现层不得直接 import `memory/`（MUST-06）。
快照序列化由调用方注入，避免 runtime 反向依赖 interfaces。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devprompt_ai.memory.event_store import SQLiteEventStore
from devprompt_ai.memory.intervention_store import SQLiteInterventionStore
from devprompt_ai.memory.run_store import SQLiteRunStore
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
            # H1 崩溃恢复：上次进程遗留的 running 一律收尾，避免前端永远看到「进行中」。
            await runs.mark_orphans_aborted(30)
            bus = EventBus(events)
            pool = SessionPool()

            # 阶段7 周期 checkpoint：service 每 5 步经此把进度落 run_events（执行体不依赖订阅）。
            async def _checkpoint(session_id: str, payload: dict[str, Any]) -> None:
                await bus.append(session_id, "agent.checkpoint", payload)

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
