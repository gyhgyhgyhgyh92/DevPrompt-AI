"""真进程 SSE：`since=N` 只补差、首帧合成快照、id 带 seq、冷启动回填。

事件由测试进程直接写入服务的临时库（WAL 允许多进程写），因此不依赖 LLM。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from devprompt_ai.memory.event_store import SQLiteEventStore


def _seed_events(db_path: str, session_id: str, count: int = 3) -> list[int]:
    store = SQLiteEventStore(db_path)

    async def _go() -> list[int]:
        await store.init_schema()
        seqs: list[int] = []
        for index in range(count):
            event = await store.append(
                session_id, "agent.step", {"index": index, "action": "probe"}, run_id="r-sse"
            )
            seqs.append(event.seq)
        return seqs

    return asyncio.run(_go())


def _read_frames(
    api: Any,
    session_id: str,
    since: int,
    want: int = 3,
    headers: dict[str, str] | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    frames: list[tuple[int, dict[str, Any]]] = []
    with api.stream(
        "GET",
        f"/api/v1/sessions/{session_id}/stream",
        params={"since": since},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        current_id: int | None = None
        for line in response.iter_lines():
            if line.startswith("id: "):
                current_id = int(line[4:].strip())
            elif line.startswith("data: ") and current_id is not None:
                frames.append((current_id, json.loads(line[6:])))
                current_id = None
                if len(frames) >= want:
                    break
    return frames


def test_sse_since_only_replays_newer_events(live_server: Any) -> None:
    db_path = str(live_server.data_dir / "live.db")
    session_id = "sse-since-case"
    seqs = _seed_events(db_path, session_id, count=3)
    assert seqs == sorted(seqs) and len(set(seqs)) == 3

    # since=seqs[0]：首帧是 seq=0 合成快照，随后只补 seq > 1 的事件
    frames = _read_frames(live_server.client, session_id, since=seqs[0], want=3)
    assert frames[0][0] == 0
    assert frames[0][1]["type"] == "snapshot"
    assert frames[0][1]["data"]["last_seq"] == seqs[-1]
    replayed = [seq for seq, _ in frames[1:]]
    assert replayed == [seq for seq in seqs if seq > seqs[0]]


def test_sse_full_replay_from_zero(live_server: Any) -> None:
    db_path = str(live_server.data_dir / "live.db")
    session_id = "sse-zero-case"
    seqs = _seed_events(db_path, session_id, count=2)

    frames = _read_frames(live_server.client, session_id, since=0, want=3)
    assert frames[0][0] == 0
    body = [payload for _, payload in frames[1:]]
    assert [item["seq"] for item in body] == seqs
    assert body[0]["type"] == "agent.step"


def test_reconnect_with_last_event_id_only_replays_newer(live_server: Any) -> None:
    """模拟真实断连：读到一半关闭，再带 Last-Event-ID 重连只补后段。"""
    db_path = str(live_server.data_dir / "live.db")
    session_id = "sse-reconnect-case"
    seqs = _seed_events(db_path, session_id, count=4)

    # 第一段：读到第 2 条真实事件就主动断开（模拟网络中断）
    first_chunk: list[int] = []
    with live_server.client.stream(
        "GET", f"/api/v1/sessions/{session_id}/stream", params={"since": 0}
    ) as response:
        for line in response.iter_lines():
            if line.startswith("id: "):
                seq = int(line[4:].strip())
                if seq > 0:
                    first_chunk.append(seq)
                if len(first_chunk) >= 2:
                    break
    assert first_chunk == seqs[:2]

    # 第二段：浏览器重连会自动带 Last-Event-ID=最后收到的 seq
    frames = _read_frames(
        live_server.client,
        session_id,
        since=0,
        want=3,
        headers={"Last-Event-ID": str(first_chunk[-1])},
    )
    assert frames[0][0] == 0
    replayed = [seq for seq, _ in frames[1:]]
    assert replayed == seqs[2:]


def test_cold_backfill_before_seq(live_server: Any) -> None:
    db_path = str(live_server.data_dir / "live.db")
    session_id = "sse-backfill-case"
    seqs = _seed_events(db_path, session_id, count=3)

    response = live_server.client.get(
        "/api/v1/events",
        params={"session_id": session_id, "before": seqs[-1], "limit": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    # before 是开区间：只回填 seq < last
    assert [item["seq"] for item in body["data"]] == seqs[:-1]
