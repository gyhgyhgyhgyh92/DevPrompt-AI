"""可观测性模块装配（三模块独立开关，2026-11-12）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
from devprompt_ai.memory.metrics_alert_store import SQLiteAlertStore
from devprompt_ai.memory.replay_store import SQLiteReplayStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore
from devprompt_ai.obs.metrics_service import MetricsService
from devprompt_ai.obs.replay_service import ReplayService
from devprompt_ai.obs.trace_service import TraceService


@dataclass
class ObsModules:
    cfg: AppConfig
    collector: Any
    trace: TraceService
    metrics: MetricsService
    replay: ReplayService
    trace_store: SQLiteTraceStore

    async def startup(self) -> None:
        await self.trace.startup(self.cfg.obs_trace_retention_days)
        await self.metrics.startup()
        await self.replay.startup()

    def apply_settings(self, cfg: AppConfig) -> None:
        """把设置变更同步到运行中的模块（独立启停，互不影响）。

        采集器始终构造为 ``TraceCollectorImpl``（关闭时只是 ``enabled=False``），
        因此运行期打开 Trace 无需重建接线；Metrics 监听器也始终注册，
        由 ``MetricsService.enabled`` 自行短路——这让三个开关都能即时生效。
        """
        self.collector.enabled = cfg.obs_trace_enabled
        self.trace.enabled = cfg.obs_trace_enabled
        self.metrics.enabled = cfg.obs_metrics_enabled
        self.replay.enabled = cfg.obs_replay_enabled
        self.cfg = cfg


def build_obs_modules(cfg: AppConfig) -> ObsModules:
    """按配置装配三模块；关闭只影响各自 API/采集，不影响其它模块读取历史数据。"""
    trace_store = SQLiteTraceStore(cfg.db_path)
    collector: Any = TraceCollectorImpl(trace_store, enabled=cfg.obs_trace_enabled, cfg=cfg)
    trace_service = TraceService(trace_store, collector, enabled=cfg.obs_trace_enabled)
    alert_store = SQLiteAlertStore(cfg.db_path, cooldown_s=cfg.obs_metrics_alert_cooldown_s)
    metrics_service = MetricsService(trace_store, alert_store, cfg, enabled=cfg.obs_metrics_enabled)
    replay_service = ReplayService(
        trace_store, SQLiteReplayStore(cfg.db_path), cfg, enabled=cfg.obs_replay_enabled
    )
    collector.add_listener(metrics_service)
    return ObsModules(
        cfg=cfg,
        collector=collector,
        trace=trace_service,
        metrics=metrics_service,
        replay=replay_service,
        trace_store=trace_store,
    )
