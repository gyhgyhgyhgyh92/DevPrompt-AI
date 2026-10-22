"""T6-9 固定事件名结构化日志（F-005 / SHOULD-08）。

实现选型注记（宪法 MUST-04 优先原生能力）：实施计划 T6-9 原文为「structlog 结构化日志」，
但 structlog 未安装且未登记技术栈（审查报告 §四未登记依赖）；标准库 logging（第 2 级）
足以承载「固定事件名 + 结构化字段 + 脱敏」要求，依宪法采用标准库实现——冲突记录见真源 §13
（2026-10-12）。事件字段为结构化 key/value（LogRecord extra），可被 handler 聚合查询。

脱敏契约（MUST-19）：事件字段不得携带用户原句与完整路径；生产 INFO 级不落盘
原句与完整路径由调用方字段约束 + 测试断言共同保证。
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger("devprompt.events")

EVENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "flow.started",
        "flow.completed",
        "recommendation.made",
        "recommendation.skipped",
        "state.truncated",
        "followup.guardrail",
        "followup.escaped",
        "decision.tools_unsupported",
        "decision.ask_args_invalid",
        "followup.task_kind",
        "followup.question_lint",
        "cache.hit",
        "cache.miss",
        "startup.repair",
        "settings.updated",
        "model_catalog.refreshed",
        "model_catalog.refresh_failed",
    }
)
"""SHOULD-08 固定事件名全集（十三名；made/skipped 同族计一项）。emit 之外的诊断日志用普通logging。

2026-10-15 移除「决策层切换」事件：决策层统一为单一 LLM 实现（无降级切换），该事件已无发射点。
2026-10-17 新增模型目录两事件：刷新成功（含模型条数）/ 刷新失败（回落旧快照）。
"""

_telemetry_enabled = True


def set_telemetry(enabled: bool) -> None:
    """遥测开关（F-604 流程与安全）：关闭后固定事件不再落盘，诊断日志不受影响。"""
    global _telemetry_enabled
    _telemetry_enabled = enabled


def is_telemetry_enabled() -> bool:
    return _telemetry_enabled


def _check_event(event: str) -> None:
    if event not in EVENT_NAMES:
        raise ValueError(f"未登记事件名：{event!r}（全集见 observability.logging.EVENT_NAMES）")


def emit(event: str, **fields: object) -> None:
    """INFO 级固定事件：消息体即事件名，结构化字段走 LogRecord extra。"""
    _check_event(event)
    if not _telemetry_enabled:
        return
    logger.info(event, extra=dict(fields))


def emit_warning(event: str, **fields: object) -> None:
    """警告级固定事件（如提问形态不合规）：不是异常，不带堆栈。"""
    _check_event(event)
    if not _telemetry_enabled:
        return
    logger.warning(event, extra=dict(fields))


def emit_error(event: str, **fields: object) -> None:
    """错误级固定事件：保留异常堆栈（recommendation.skipped 异常路径）。"""
    _check_event(event)
    if not _telemetry_enabled:
        return
    logger.exception(event, extra=dict(fields))
