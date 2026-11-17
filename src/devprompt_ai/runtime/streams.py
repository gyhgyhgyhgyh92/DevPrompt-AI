"""SSE 帧编码：`id:` 带 seq，断线重连可直接用 Last-Event-ID 补差。"""

from __future__ import annotations

import json

from devprompt_ai.domain.events import RunEvent

#: 心跳注释帧：不进事件日志、不占 seq。
PING_FRAME = ": ping\n\n"


def sse_frame(event: RunEvent) -> str:
    if event.type == "ping":
        return PING_FRAME
    body = json.dumps(event.to_wire(), ensure_ascii=False)
    return f"id: {event.seq}\ndata: {body}\n\n"
