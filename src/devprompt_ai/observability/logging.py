"""T6-9 固定事件名结构化日志（F-005 / SHOULD-08）。

实现选型注记（宪法 MUST-04 优先原生能力）：实施计划 T6-9 原文为「structlog 结构化日志」，
但 structlog 未安装且未登记技术栈（审查报告 §四未登记依赖）；标准库 logging（第 2 级）
足以承载「固定事件名 + 结构化字段 + 脱敏」要求，依宪法采用标准库实现——冲突记录见真源 §13
（2026-10-12）。事件字段为结构化 key/value（LogRecord extra），可被 handler 聚合查询。

脱敏契约（MUST-19）：事件字段不得携带用户原句与完整路径；生产 INFO 级不落盘
原句与完整路径由调用方字段约束 + 测试断言共同保证。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

logger = logging.getLogger("devprompt.events")

EVENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "flow.started",
        "flow.completed",
        "recommendation.made",
        "recommendation.skipped",
        "recommendation.recovered",
        "state.truncated",
        # Reflection（2026-11-22）：外部经验库旁路——recalled/recorded 为常规，
        # skipped 为未配置，failed 为降级（只记操作名与异常类型，不记内容）
        "reflection.recalled",
        "reflection.recorded",
        "reflection.skipped",
        "reflection.failed",
        "followup.guardrail",
        "followup.clarifications_invalidated",
        "followup.escaped",
        "decision.tools_unsupported",
        "decision.ask_args_invalid",
        "decision.probe_empty",
        "retrieval.impact",
        "followup.task_kind",
        "followup.question_lint",
        "followup.question_suppressed",
        "cache.hit",
        "cache.miss",
        "startup.repair",
        "settings.updated",
        "model_catalog.refreshed",
        "model_catalog.refresh_failed",
        "agent.step",
        "agent.hook_halt",
        "agent.sensorium",
        "agent.loop_terminated",
        "agent.turn_token_budget_exceeded",
        "delegation.skipped_resume",
        "delegation.reused",
        "settings.skills_updated",
        "settings.mcp_updated",
        "settings.reflection_updated",
        "skill.selected",
        "skill.budget_truncated",
        "mcp.connected",
        "mcp.connect_failed",
        "mcp.tool_called",
        "mcp.tool_failed",
        "mcp.approval_requested",
        "mcp.approval_timeout",
        "mcp.approval_denied",
        "evidence.reused",
        "evidence.stale_reprobe",
        "evidence.target_changed",
        "generate.fallback",
        # 生成/决策调用失败留痕（2026-11-15）：此前只能靠「trace 少一条 response」推断
        "llm.error",
        # 排序失败回退分数第一名（2026-11-15）：降级可见，不静默
        "decision.rank_degraded",
        "evidence.claim_uncovered",
        "evidence.claim_undeclared",
        "evidence.anchor_invalid",
        "delivery.gate",
        "session.rolled_back",
        "session.model_switch",
        "agent.finish_gate_blocked",
        "context.overflow_retry",
        "delegation.rejected",
        "delegation.wave",
        "context.append_violation",
        "context.compacted",
        "followup.expect_unmet",
        "hook.failed",
        "hook.ran",
        "evidence.stale_on_deliver",
        "llm.request_params",
        "context.tier_changed",
        "trace.write_failed",
        "domain.classify_failed",
        "domain.classify_invalid",
        "domain.classify_low_confidence",
        "domain.inherit_invalid",
        "agent.action_filtered",
        # 同轮补充检索工具（2026-11-18）：工具被调用/失败留痕；只记规模不记检索词。
        "tool.search_invoked",
        "tool.search_failed",
    }
)
"""SHOULD-08 固定事件名全集（made/skipped 同族计一项）。emit 之外的诊断日志用普通 logging。

2026-10-15 移除「决策层切换」事件：决策层统一为单一 LLM 实现（无降级切换），该事件已无发射点。
2026-10-17 新增模型目录两事件：刷新成功（含模型条数）/ 刷新失败（回落旧快照）。
2026-11-04 星型拓扑新增两事件：每步动作（action/index/duration_ms）与循环终止（reason）。
2026-11-07 新增 decision.probe_empty：模型未给出任何判定（judgments 为空，参数畸形分支）。
2026-11-08 新增 session.model_switch：F10 会话级模型热切换。
2026-11-14 新增领域路由三事件：LLM 分类失败/非法领域回退、会话继承载荷畸形。
"""

_telemetry_enabled = True
_FILE_SINK_INSTALLED = False


class _JsonlFormatter(logging.Formatter):
    """把固定事件的 extra 字段序列化成单行 JSON；不落用户原句由调用方字段约束保证。"""

    def format(self, record: logging.LogRecord) -> str:
        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }
        fields = {key: value for key, value in record.__dict__.items() if key not in reserved}
        return json.dumps(
            {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                **fields,
            },
            ensure_ascii=False,
            default=str,
        )


def install_file_sink(log_dir: str) -> None:
    """幂等挂载 JSONL 文件 sink；失败只降级为控制台，不影响业务。"""
    global _FILE_SINK_INSTALLED
    if _FILE_SINK_INSTALLED or not log_dir:
        return
    try:
        directory = Path(log_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / "events.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(_JsonlFormatter())
        logger.addHandler(handler)
        # 固定事件大量走 INFO；默认 WARNING 会让它们根本不落盘。
        logger.setLevel(logging.INFO)
        _FILE_SINK_INSTALLED = True
    except OSError:
        logger.warning("event_log_sink_unavailable", exc_info=True)


def event_log_path(log_dir: str) -> Path:
    return Path(log_dir).expanduser() / "events.jsonl"


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
