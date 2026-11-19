"""Metrics 模块应用服务：聚合查询、阈值评估与告警历史。"""

from __future__ import annotations

from typing import Any

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.obs.contract.query import AggregateQuery, MetricSeries
from devprompt_ai.domain.obs.metrics.rules import MetricThresholds, evaluate
from devprompt_ai.memory.metrics_alert_store import SQLiteAlertStore
from devprompt_ai.memory.trace_store import SQLiteTraceStore


class MetricsService:
    def __init__(
        self,
        trace_store: SQLiteTraceStore,
        alerts: SQLiteAlertStore,
        cfg: AppConfig,
        *,
        enabled: bool = True,
    ) -> None:
        self._trace_store = trace_store
        self._alerts = alerts
        self._cfg = cfg
        self.enabled = enabled

    def thresholds(self) -> MetricThresholds:
        return MetricThresholds(
            p95_ms_warn=self._cfg.obs_metrics_p95_warn_ms,
            error_rate_warn=self._cfg.obs_metrics_error_rate_warn,
            token_warn=self._cfg.obs_metrics_token_warn,
            tool_failure_rate_warn=self._cfg.obs_metrics_tool_failure_warn,
            refusal_rate_warn=self._cfg.obs_metrics_refusal_warn,
            critical_multiplier=self._cfg.obs_metrics_critical_multiplier,
        )

    async def startup(self) -> None:
        await self._alerts.init_schema()

    async def summary(self, query: AggregateQuery) -> list[MetricSeries]:
        return await self._trace_store.aggregate(query)

    async def evaluate(self, *, session_id: str = "", trace_id: str = "") -> None:
        if not session_id and not trace_id:
            return
        series = await self._trace_store.aggregate(
            AggregateQuery(session_id=session_id, trace_id=trace_id, group_by="kind")
        )
        scope_kind = "trace" if trace_id else "session"
        scope_key = trace_id or session_id
        drafts = evaluate(
            series,
            self.thresholds(),
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        await self._alerts.sync_alerts(drafts, scope_kind=scope_kind, scope_key=scope_key)

    async def on_trace_completed(self, trace_id: str, session_id: str) -> None:
        if not self.enabled:
            return
        await self.evaluate(trace_id=trace_id, session_id=session_id)

    async def alerts(self, *, status: str = "", limit: int = 50, offset: int = 0) -> list[Any]:
        return await self._alerts.list_alerts(status=status, limit=limit, offset=offset)

    def config_payload(self) -> dict[str, Any]:
        thresholds = self.thresholds()
        return {
            "p95_ms_warn": thresholds.p95_ms_warn,
            "error_rate_warn": thresholds.error_rate_warn,
            "token_warn": thresholds.token_warn,
            "tool_failure_rate_warn": thresholds.tool_failure_rate_warn,
            "refusal_rate_warn": thresholds.refusal_rate_warn,
            "critical_multiplier": thresholds.critical_multiplier,
            "alert_cooldown_s": self._cfg.obs_metrics_alert_cooldown_s,
        }
