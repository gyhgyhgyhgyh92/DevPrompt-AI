"""固定事件日志只读 API：按事件名/请求 ID 过滤，倒序读 JSONL 尾部。"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query

from devprompt_ai.config import AppConfig
from devprompt_ai.interfaces.api.schemas import ApiResponse
from devprompt_ai.observability.logging import event_log_path
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/obs/logs", tags=["obs-logs"])


class LogEventsPayload(BaseModel):
    items: list[dict[str, Any]]
    limit: int
    total: int


def _read_events(
    path: Any,
    *,
    event: str,
    request_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """读文件尾部；畸形行跳过，避免一条坏日志让端点 500。"""
    from pathlib import Path

    file = Path(path)
    if not file.exists():
        return []
    rows: list[dict[str, Any]] = []
    with file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if event and row.get("event") != event:
                continue
            if request_id and row.get("request_id") != request_id:
                continue
            rows.append(row)
    return rows[-limit:][::-1]


@router.get("/events", response_model=ApiResponse[LogEventsPayload])
async def events(
    event: str = "",
    request_id: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ApiResponse[LogEventsPayload]:
    path = event_log_path(AppConfig().log_dir)
    rows = _read_events(path, event=event, request_id=request_id, limit=limit)
    return ApiResponse(data=LogEventsPayload(items=rows, limit=limit, total=len(rows)))
