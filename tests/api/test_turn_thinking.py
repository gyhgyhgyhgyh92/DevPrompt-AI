"""历史轮思考帧重建（2026-11-15）：归属规则、字段转换与 output 截断。

run_events 本就是完整的 thought/action 记录（含工具 output），历史轮由它还原；
这里只测纯函数部分——IO 分页由集成/端到端兜底。
"""

from devprompt_ai.domain.events import RunEvent
from devprompt_ai.interfaces.api.routes import (
    _segments_for_turn,
    _thinking_payload,
)


def _ev(seq: int, event_type: str, payload: dict[str, object] | None = None) -> RunEvent:
    return RunEvent(session_id="s1", seq=seq, type=event_type, payload=dict(payload or {}))


def _sample_events() -> list[RunEvent]:
    return [
        _ev(1, "run.started", {"run_id": "r1"}),
        _ev(2, "thought", {"text": "开始检索", "phase": "RETRIEVING"}),
        _ev(
            3,
            "action",
            {
                "title": "定位符号定义",
                "detail": "rg -n page .",
                "scope": "命中 4 行",
                "output": "o1",
                "status": "ok",
                "duration_ms": 40,
                "phase": "RETRIEVING",
            },
        ),
        _ev(4, "snapshot", {"current_turn_id": "t1"}),
        _ev(5, "stop", {"status": "ask"}),
        # followup 段：无 snapshot，应归到此前最近一轮 t1
        _ev(6, "run.started", {"run_id": "followup-x", "mode": "followup"}),
        _ev(7, "thought", {"text": "重新研判", "phase": "ASKING"}),
        _ev(8, "stop", {"status": "done"}),
        _ev(9, "run.started", {"run_id": "r2"}),
        _ev(10, "thought", {"text": "第二轮检索", "phase": "RETRIEVING"}),
        _ev(11, "snapshot", {"current_turn_id": "t2"}),
        _ev(12, "stop", {"status": "done"}),
    ]


def test_segments_owner_by_current_turn_id() -> None:
    """段归属：snapshot 的 current_turn_id 决定轮次；无 snapshot 的段归前一回合。"""
    events = _sample_events()

    first = _segments_for_turn(events, "t1")
    second = _segments_for_turn(events, "t2")

    assert [event.seq for event in first] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [event.seq for event in second] == [9, 10, 11, 12]


def test_thinking_payload_maps_frames() -> None:
    """thought → text 帧；action → 带 output/耗时/状态的卡片帧；空文字不占位。"""
    shots = _thinking_payload(_segments_for_turn(_sample_events(), "t1"))

    assert [shot["kind"] for shot in shots] == ["text", "action", "text"]
    action = shots[1]
    assert action["title"] == "定位符号定义"
    assert action["output"] == "o1"
    assert action["duration_ms"] == 40
    assert action["phase"] == "RETRIEVING"
    assert shots[2]["phase"] == "ASKING"


def test_output_is_clipped() -> None:
    """单帧 output 超过 2000 字必须截断，避免详情接口响应膨胀。"""
    events = [_ev(1, "action", {"title": "x", "output": "a" * 3000})]

    shots = _thinking_payload(events)

    assert len(shots[0]["output"]) < 3000
    assert "已截断" in shots[0]["output"]


def test_unknown_turn_returns_empty() -> None:
    """不属于该轮的事件段一律不返回（不串轮、不伪造）。"""
    assert _segments_for_turn(_sample_events(), "missing") == []
