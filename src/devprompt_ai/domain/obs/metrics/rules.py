"""Metrics 阈值规则（纯函数，MUST-08：阈值只在后端）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from devprompt_ai.domain.obs.contract.query import AlertDraft, MetricSeries


@dataclass(frozen=True, slots=True)
class MetricThresholds:
    p95_ms_warn: int = 5000
    error_rate_warn: float = 0.2
    token_warn: int = 50000
    tool_failure_rate_warn: float = 0.2
    #: 模型拒绝率 = llm.response 中 failed 占比（失败分支由 TracedGenerator 记录）
    refusal_rate_warn: float = 0.2
    critical_multiplier: float = 2.0


def _severity(observed: float, threshold: float, multiplier: float) -> str:
    return "critical" if threshold > 0 and observed > threshold * multiplier else "warning"


def evaluate(
    series: Sequence[MetricSeries],
    thresholds: MetricThresholds,
    *,
    scope_kind: str,
    scope_key: str,
) -> list[AlertDraft]:
    """对一次聚合结果执行全部规则；空数据不产生告警。"""
    points = [point for item in series for point in item.points]
    if not points:
        return []
    total = sum(point.count for point in points)
    failed = sum(point.failed for point in points)
    drafts: list[AlertDraft] = []

    worst_p95 = max((point.p95_ms or 0) for point in points)
    if worst_p95 > thresholds.p95_ms_warn:
        drafts.append(
            AlertDraft(
                rule_id="p95_duration",
                severity=_severity(
                    worst_p95, thresholds.p95_ms_warn, thresholds.critical_multiplier
                ),
                scope_kind=scope_kind,
                scope_key=scope_key,
                metric="p95_ms",
                observed=float(worst_p95),
                threshold=float(thresholds.p95_ms_warn),
                message=f"节点 P95 耗时 {worst_p95}ms 超过阈值 {thresholds.p95_ms_warn}ms",
            )
        )

    error_rate = failed / total if total else 0.0
    if error_rate > thresholds.error_rate_warn:
        drafts.append(
            AlertDraft(
                rule_id="error_rate",
                severity=_severity(
                    error_rate, thresholds.error_rate_warn, thresholds.critical_multiplier
                ),
                scope_kind=scope_kind,
                scope_key=scope_key,
                metric="error_rate",
                observed=error_rate,
                threshold=thresholds.error_rate_warn,
                message=f"事件失败率 {error_rate:.2%} 超过阈值 {thresholds.error_rate_warn:.2%}",
            )
        )

    tokens = sum(point.tokens for point in points)
    if tokens > thresholds.token_warn:
        drafts.append(
            AlertDraft(
                rule_id="token_budget",
                severity=_severity(tokens, thresholds.token_warn, thresholds.critical_multiplier),
                scope_kind=scope_kind,
                scope_key=scope_key,
                metric="tokens",
                observed=float(tokens),
                threshold=float(thresholds.token_warn),
                message=f"Token 用量 {tokens} 超过阈值 {thresholds.token_warn}",
            )
        )

    tool_points = [
        point
        for item in series
        if item.dimension == "kind" and item.key == "tool.result"
        for point in item.points
    ]
    tool_total = sum(point.count for point in tool_points)
    tool_failed = sum(point.failed for point in tool_points)
    tool_rate = tool_failed / tool_total if tool_total else 0.0
    if tool_rate > thresholds.tool_failure_rate_warn:
        drafts.append(
            AlertDraft(
                rule_id="tool_failure_rate",
                severity=_severity(
                    tool_rate, thresholds.tool_failure_rate_warn, thresholds.critical_multiplier
                ),
                scope_kind=scope_kind,
                scope_key=scope_key,
                metric="tool_failure_rate",
                observed=tool_rate,
                threshold=thresholds.tool_failure_rate_warn,
                message=(
                    f"工具失败率 {tool_rate:.2%} 超过阈值 {thresholds.tool_failure_rate_warn:.2%}"
                ),
            )
        )

    # 模型拒绝率（2026-11-19）：llm.response 的 failed 占比。分子来自 TracedGenerator
    # 失败分支；空回答/交付门拦截已有 StopReason，不并入此口径，避免混淆模型与流程失败。
    llm_points = [
        point
        for item in series
        if item.dimension == "kind" and item.key == "llm.response"
        for point in item.points
    ]
    llm_total = sum(point.count for point in llm_points)
    llm_failed = sum(point.failed for point in llm_points)
    refusal_rate = llm_failed / llm_total if llm_total else 0.0
    if refusal_rate > thresholds.refusal_rate_warn:
        drafts.append(
            AlertDraft(
                rule_id="refusal_rate",
                severity=_severity(
                    refusal_rate, thresholds.refusal_rate_warn, thresholds.critical_multiplier
                ),
                scope_kind=scope_kind,
                scope_key=scope_key,
                metric="refusal_rate",
                observed=refusal_rate,
                threshold=thresholds.refusal_rate_warn,
                message=(
                    f"模型拒绝率 {refusal_rate:.2%} 超过阈值 {thresholds.refusal_rate_warn:.2%}"
                ),
            )
        )
    return drafts
