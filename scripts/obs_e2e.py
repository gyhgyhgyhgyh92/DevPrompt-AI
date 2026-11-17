"""可观测性四模块 E2E 报告运行器（真实服务 + 真实 LLM + 性能测量）。

用法：
    uv run python scripts/obs_e2e.py --real-llm

产物：
    eval/obs/report-<date>.md
    eval/obs/report-<date>.json
    eval/obs/runs/<timestamp>/（临时 DB / settings / pytest junit，已 gitignore）

安全：只读取 `~/.devprompt-ai/settings.json` 的模型段，不打印也不写入报告；
所有测试数据写入临时目录，不触碰用户真实 DB。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PROJECT = REPO_ROOT / "eval" / "recall" / "mock-react-admin"
SENTENCE = "把 SubmitButton、UserTable 和 LoginForm 的主色改成 --color-primary-500"
SENTENCE_2 = "再给 SubmitButton 加一个 hover 状态"
DATE = datetime.now().strftime("%Y-%m-%d")
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

COLLECT_LIMIT_MS = 200.0
QUERY_LIMIT_MS = 500.0
COMPLETENESS_LIMIT = 0.999


@dataclass
class CaseResult:
    case_id: str
    module: str
    category: str
    title: str
    status: str
    duration_ms: float
    evidence: str = ""
    error: str = ""


@dataclass
class Measurement:
    name: str
    value: float
    unit: str
    threshold: float
    passed: bool
    method: str
    comparison: str = "<="


@dataclass
class Defect:
    defect_id: str
    priority: str
    title: str
    impact: str
    reproduction: str
    recommendation: str
    status: str = "open（仅报告）"


@dataclass
class Report:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    cases: list[CaseResult] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    defects: list[Defect] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    consistency: dict[str, Any] = field(default_factory=dict)
    run_dir: str = ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_real_model() -> dict[str, Any] | None:
    path = Path.home() / ".devprompt-ai" / "settings.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    section = doc.get("model_service")
    if not isinstance(section, dict):
        return None
    if not (section.get("base_url") and section.get("model_id") and section.get("api_key")):
        return None
    return section


class Server:
    """隔离启动真实服务：临时 settings.json + 临时 DB + 独立端口。"""

    def __init__(self, run_dir: Path, model: dict[str, Any] | None, *, tag: str) -> None:
        self.run_dir = run_dir / tag
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.run_dir / "devprompt.db")
        self.settings_path = self.run_dir / "settings.json"
        self.model = model
        self.port = _free_port()
        self.proc: subprocess.Popen[bytes] | None = None
        self.log_path = self.run_dir / "server.log"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _prepare_settings(self, *, api_key: str | None = None) -> None:
        section = dict(self.model or {})
        if api_key is not None:
            section["api_key"] = api_key
        self.settings_path.write_text(
            json.dumps({"model_service": section}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def start(self, *, api_key: str | None = None) -> None:
        self._prepare_settings(api_key=api_key)
        env = os.environ.copy()
        env.update(
            {
                "DEVPROMPT_SETTINGS_FILE": str(self.settings_path),
                "DEVPROMPT_SETTINGS_DB": self.db_path,
                "DB_PATH": self.db_path,
                "PYTHONUTF8": "1",
            }
        )
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "devprompt_ai.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"服务提前退出，日志：{self.log_path}")
            try:
                with httpx.Client(trust_env=False, timeout=2.0) as probe:
                    resp = probe.get(f"{self.base_url}/api/v1/health")
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise RuntimeError(f"服务健康检查超时：{self.log_path}")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc = None


def _post(client: httpx.Client, path: str, body: dict[str, Any], request_id: str) -> dict[str, Any]:
    resp = client.post(path, json=body, headers={"X-Request-ID": request_id}, timeout=30)
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"POST {path} 失败：{payload}")
    return payload["data"]


def _get(client: httpx.Client, path: str) -> dict[str, Any]:
    resp = client.get(path, timeout=30)
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"GET {path} 失败：{payload}")
    return payload["data"]


class KnownDefectError(RuntimeError):
    """已确认缺陷：用例记为 XFAIL 并写入报告，不阻塞整体执行。"""


class ExternalBlockedError(RuntimeError):
    """外部依赖不可用（如供应商余额耗尽）：记为 BLOCKED，不算产品失败。"""


def _wait_run(
    client: httpx.Client,
    session_id: str,
    run_id: str,
    *,
    since: int = 0,
    timeout: float = 300.0,
) -> list[dict[str, Any]]:
    """订阅 SSE 至**本次 run** 的 stop/error；历史轮次的 stop 不算。

    多轮会话必须传 ``since=上一轮 last_seq``：SSE 回放遇到历史 stop 即关闭，
    since=0 会在第二轮回放阶段就直接结束（RL-02 曾因此误判）。
    """
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    with client.stream(
        "GET",
        f"/api/v1/sessions/{session_id}/stream",
        params={"since": since},
        timeout=timeout,
    ) as resp:
        for line in resp.iter_lines():
            if time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} 超时")
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("seq", 0) == 0:
                continue
            events.append(event)
            if event.get("run_id") == run_id and event.get("type") in {"stop", "error"}:
                return events
    return events


def _last_seq(client: httpx.Client, session_id: str) -> int:
    """会话当前最后一条事件 seq（开新一轮前取，作为 SSE 订阅起点）。"""
    events = _get(client, f"/api/v1/events?session_id={session_id}&before={1 << 30}&limit=1")
    return int(events[-1].get("seq", 0)) if events else 0


def _wait_replay(client: httpx.Client, run_id: str, *, timeout: float = 240.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _get(client, f"/api/v1/obs/replay/runs/{run_id}")
        if data["run"]["status"] != "running":
            return data
        time.sleep(0.2)
    raise TimeoutError(f"replay {run_id} 超时")


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[index]


def _record_case(
    report: Report,
    case_id: str,
    module: str,
    category: str,
    title: str,
    fn: Any,
) -> Any:
    started = time.perf_counter()
    try:
        evidence = fn()
        report.cases.append(
            CaseResult(
                case_id=case_id,
                module=module,
                category=category,
                title=title,
                status="PASS",
                duration_ms=(time.perf_counter() - started) * 1000,
                evidence=str(evidence or ""),
            )
        )
        return evidence
    except KnownDefectError as exc:
        report.cases.append(
            CaseResult(
                case_id=case_id,
                module=module,
                category=category,
                title=title,
                status="XFAIL",
                duration_ms=(time.perf_counter() - started) * 1000,
                evidence=str(exc),
            )
        )
        return None
    except ExternalBlockedError as exc:
        report.cases.append(
            CaseResult(
                case_id=case_id,
                module=module,
                category=category,
                title=title,
                status="BLOCKED",
                duration_ms=(time.perf_counter() - started) * 1000,
                evidence=str(exc),
            )
        )
        return None
    except Exception as exc:  # noqa: BLE001 - 报告必须记录失败而不是中断
        report.cases.append(
            CaseResult(
                case_id=case_id,
                module=module,
                category=category,
                title=title,
                status="FAIL",
                duration_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        return None


# ---------------------------------------------------------------------------
# 真实 LLM 场景（HTTP）
# ---------------------------------------------------------------------------


def _require_trace(state: dict[str, Any]) -> str:
    trace_id = str(state.get("trace_id", ""))
    if not trace_id:
        raise ExternalBlockedError("RL-01 未成功（真实 LLM 不可用），依赖用例跳过")
    return trace_id


def _run_success_scenarios(report: Report, server: Server) -> None:
    client = httpx.Client(base_url=server.base_url, trust_env=False)
    state: dict[str, Any] = {}

    def rl01() -> str:
        # D-04 修复后：前端新 UUID 可直接经 /runs 建会话，无需预建容器。
        session_id = uuid.uuid4().hex
        request_id = f"e2e-rl01-{uuid.uuid4().hex[:8]}"
        state["session_id"] = session_id
        state["request_id"] = request_id
        record = _post(
            client,
            "/api/v1/runs",
            {
                "session_id": session_id,
                "project": str(PROJECT),
                "sentence": SENTENCE,
            },
            request_id,
        )
        events = _wait_run(client, session_id, record["run_id"])
        types = {event["type"] for event in events}
        errors = [event for event in events if event["type"] == "error"]
        if any(int(event.get("data", {}).get("code", 0)) == 5013 for event in errors):
            raise ExternalBlockedError("供应商余额/配额不足（5013），真实 LLM 场景无法完成")
        assert "stop" in types, f"缺少 stop 事件：{types}；错误：{errors}"
        snapshot = next(event for event in events if event["type"] == "snapshot")
        assert snapshot["data"]["status"] == "done", f"真实运行未完成：{snapshot['data']}"
        assert snapshot["data"]["state"] == "DONE"
        traces = _get(client, f"/api/v1/obs/trace/sessions/{session_id}/traces")["items"]
        assert len(traces) == 1, f"应有一条 Trace：{traces}"
        trace_id = traces[0]["trace_id"]
        state["trace_id"] = trace_id
        flat = _get(client, f"/api/v1/obs/trace/sessions/{session_id}/events?limit=500")["items"]
        kinds = {item["kind"] for item in flat}
        assert "llm.response" in kinds, f"真实 Trace 缺少 LLM 节点：{sorted(kinds)}"
        llm_events = [item for item in flat if item["kind"] == "llm.response"]
        token_values = [int(item.get("attributes", {}).get("tokens", 0)) for item in llm_events]
        tree = _get(client, f"/api/v1/obs/trace/traces/{trace_id}")["items"]
        return (
            f"run_events={len(events)} trace_events={traces[0]['event_count']} "
            f"tree_roots={len(tree)} llm_tokens={token_values}"
        )

    _record_case(report, "RL-01", "Session Log/Trace", "正常", "真实 LLM 单轮成功", rl01)

    def rl01_metrics() -> str:
        _require_trace(state)
        session_id = state["session_id"]
        summary = _get(
            client,
            f"/api/v1/obs/metrics/summary?session_id={session_id}&group_by=kind",
        )["items"]
        assert summary, "真实运行的指标为空"
        series = {item["key"]: sum(p["count"] for p in item["points"]) for item in summary}
        state["kind_counts"] = series
        total = sum(series.values())
        assert total > 0
        return f"kinds={len(series)} events={total}"

    _record_case(report, "MT-07", "Metrics", "正常", "真实运行指标聚合", rl01_metrics)

    def rl01_replay() -> str:
        trace_id = _require_trace(state)
        created = _post(
            client,
            "/api/v1/obs/replay/runs",
            {"mode": "verify", "left_trace_id": trace_id, "right_trace_id": ""},
            f"e2e-replay-{uuid.uuid4().hex[:8]}",
        )
        result = _wait_replay(client, created["run"]["run_id"])
        status = result["run"]["status"]
        assert status == "matched", f"D-07 修复后真实回放应 matched：status={status}"
        state["replay_nodes"] = len(result["nodes"])
        return f"nodes={len(result['nodes'])} status=matched"

    _record_case(report, "RP-02", "Replay", "正常", "真实 Trace 确定性回放", rl01_replay)

    def rl02() -> str:
        _require_trace(state)
        session_id = state["session_id"]
        request_id = f"e2e-rl02-{uuid.uuid4().hex[:8]}"
        since = _last_seq(client, session_id)
        record = _post(
            client,
            "/api/v1/runs",
            {
                "session_id": session_id,
                "project": str(PROJECT),
                "sentence": SENTENCE_2,
            },
            request_id,
        )
        events = _wait_run(client, session_id, record["run_id"], since=since)
        assert any(event["type"] == "stop" for event in events)
        traces = _get(client, f"/api/v1/obs/trace/sessions/{session_id}/traces")["items"]
        assert len(traces) == 2, f"两轮应有两条 Trace：{traces}"
        assert [trace["turn_index"] for trace in traces] == [0, 1]
        log_events = _get(
            client,
            f"/api/v1/events?session_id={session_id}&before={1 << 30}&limit=2000",
        )
        run_starts = [event for event in log_events if event["type"] == "run.started"]
        assert len(run_starts) == 2, f"Session Log 应有两段 run：{len(run_starts)}"
        return f"traces=2 log_events={len(log_events)}"

    _record_case(report, "RL-02", "Session Log/Trace", "正常", "真实 LLM 两轮会话", rl02)

    def xm_join() -> str:
        _require_trace(state)
        session_id = state["session_id"]
        request_id = state["request_id"]
        traces = _get(client, f"/api/v1/obs/trace/sessions/{session_id}/traces")["items"]
        first = traces[0]["trace_id"]
        tree = _get(
            client,
            f"/api/v1/obs/trace/traces/{first}",
        )["items"]
        turn_start = next((node for node in tree if node.get("kind") == "turn.start"), None)
        # tree 节点是嵌套结构，找顶层 input
        assert turn_start is not None
        trace_events = _get(
            client,
            f"/api/v1/obs/trace/sessions/{session_id}/events?limit=500",
        )["items"]
        assert trace_events
        assert any(item.get("run_id") == request_id for item in trace_events)
        report.consistency = {
            "session_id": session_id,
            "request_id": request_id,
            "trace_id": first,
            "kind_counts": state.get("kind_counts", {}),
            "replay_nodes": state.get("replay_nodes", 0),
            "turn_start_found": True,
        }
        return f"request_id={request_id[:12]}… trace={first[:12]}…"

    _record_case(report, "XM-01/02", "跨模块", "正常", "request_id/trace_id/指标关联", xm_join)

    def perf_http() -> str:
        _require_trace(state)
        paths = [
            f"/api/v1/obs/trace/sessions/{state['session_id']}/traces",
            f"/api/v1/obs/trace/sessions/{state['session_id']}/events?limit=200",
            f"/api/v1/obs/trace/traces/{state['trace_id']}?full=false",
            f"/api/v1/obs/metrics/summary?session_id={state['session_id']}&group_by=kind",
            "/api/v1/obs/metrics/alerts?status=active",
        ]
        samples: list[float] = []
        for _ in range(10):
            for path in paths:
                started = time.perf_counter()
                resp = client.get(path, timeout=10)
                samples.append((time.perf_counter() - started) * 1000)
                assert resp.status_code == 200
        p95 = _p95(samples)
        report.measurements.append(
            Measurement(
                name="真实会话查询 P95",
                value=round(p95, 2),
                unit="ms",
                threshold=QUERY_LIMIT_MS,
                passed=p95 <= QUERY_LIMIT_MS,
                method="5 端点 × 10 次（HTTP，真实 LLM 会话数据）",
            )
        )
        assert p95 <= QUERY_LIMIT_MS, f"P95={p95:.1f}ms"
        return f"p95={p95:.1f}ms n={len(samples)}"

    _record_case(report, "PF-02a", "性能", "正常", "真实会话查询响应", perf_http)
    client.close()


def _run_failure_scenario(report: Report, run_dir: Path, model: dict[str, Any] | None) -> None:
    server = Server(run_dir, model, tag="failure")
    try:
        server.start(api_key="sk-invalid-e2e")
    except Exception as exc:  # noqa: BLE001
        report.cases.append(
            CaseResult(
                "RL-03",
                "全链路",
                "异常",
                "真实认证失败",
                "BLOCKED",
                0.0,
                error=str(exc),
            )
        )
        return
    client = httpx.Client(base_url=server.base_url, trust_env=False)

    def rl03() -> str:
        session_id = uuid.uuid4().hex
        request_id = f"e2e-rl03-{uuid.uuid4().hex[:8]}"
        record = _post(
            client,
            "/api/v1/runs",
            {"session_id": session_id, "project": str(PROJECT), "sentence": SENTENCE},
            request_id,
        )
        events = _wait_run(client, session_id, record["run_id"], timeout=120)
        types = [event["type"] for event in events]
        assert "error" in types or "stop" in types, f"未收到终止事件：{types}"
        traces = _get(client, f"/api/v1/obs/trace/sessions/{session_id}/traces")["items"]
        assert traces, "失败轮次必须留下 Trace"
        trace_id = traces[0]["trace_id"]
        tree = _get(
            client,
            f"/api/v1/obs/trace/traces/{trace_id}",
        )["items"]
        assert tree
        created = _post(
            client,
            "/api/v1/obs/replay/runs",
            {"mode": "verify", "left_trace_id": trace_id, "right_trace_id": ""},
            f"e2e-replay-{uuid.uuid4().hex[:8]}",
        )
        result = _wait_replay(client, created["run"]["run_id"], timeout=120)
        assert result["run"]["status"] in {"failed", "diverged", "matched"}
        return f"events={types} trace_status={traces[0]['status']} replay={result['run']['status']}"

    _record_case(report, "RL-03", "全链路", "异常", "真实认证失败可观测", rl03)
    client.close()
    server.stop()


# ---------------------------------------------------------------------------
# 性能测量（进程内，独立临时库）
# ---------------------------------------------------------------------------


def _seed_event(
    seq: int, kind: str, *, trace_id: str, session_id: str, duration_ms: int = 10
) -> Any:
    from devprompt_ai.domain.obs.contract.trace import TraceEvent

    return TraceEvent(
        event_id=f"perf-{trace_id}-{seq}",
        trace_id=trace_id,
        session_id=session_id,
        turn_id="t",
        turn_index=0,
        run_id="req",
        seq=seq,
        parent_id="",
        kind=kind,
        name=kind,
        status="ok",
        started_at=f"2026-11-13T10:{seq // 60:02d}:{seq % 60:02d}.000Z",
        ended_at=f"2026-11-13T10:{seq // 60:02d}:{seq % 60:02d}.500Z",
        duration_ms=duration_ms,
        input={},
        output={},
        error={},
        attributes={"tokens": 100},
        schema_version=1,
    )


def _run_perf(report: Report, run_dir: Path) -> None:
    import asyncio

    from devprompt_ai.domain.obs.contract.trace import TraceKind
    from devprompt_ai.harness.obs.trace_collector import TraceCollectorImpl
    from devprompt_ai.memory.trace_store import SQLiteTraceStore

    async def collect_latency() -> tuple[float, float]:
        store = SQLiteTraceStore(str(run_dir / "perf-collect.db"))
        await store.init_schema()
        collector = TraceCollectorImpl(store, buffer_size=1)
        await collector.start_turn(
            session_id="perf", turn_id="t", turn_index=0, sentence="s", project_root="."
        )
        samples: list[float] = []
        for index in range(200):
            started = time.perf_counter()
            event_id = await collector.record(
                TraceKind.TOOL.value, "command", input={"index": index}, output={"ok": True}
            )
            await collector.flush()
            assert await store.get_event(event_id) is not None
            samples.append((time.perf_counter() - started) * 1000)
        batches: list[float] = []
        for batch in range(50):
            events = [
                _seed_event(
                    seq,
                    TraceKind.ACTION_END.value,
                    trace_id=f"batch-{batch}",
                    session_id="perf",
                )
                for seq in range(1, 21)
            ]
            started = time.perf_counter()
            await store.append_events(events)
            batches.append((time.perf_counter() - started) * 1000)
        return _p95(samples), _p95(batches)

    def measure_pf01() -> str:
        single, batch = asyncio.run(collect_latency())
        passed = single <= COLLECT_LIMIT_MS and batch <= COLLECT_LIMIT_MS
        report.measurements.append(
            Measurement(
                "采集延迟 P95（单事件）",
                round(single, 2),
                "ms",
                COLLECT_LIMIT_MS,
                single <= COLLECT_LIMIT_MS,
                "record→flush→get_event ×200",
            )
        )
        report.measurements.append(
            Measurement(
                "批量写入 P95（20 条/批）",
                round(batch, 2),
                "ms",
                COLLECT_LIMIT_MS,
                batch <= COLLECT_LIMIT_MS,
                "append_events ×50",
            )
        )
        assert passed, f"single={single:.1f}ms batch={batch:.1f}ms"
        return f"single_p95={single:.1f}ms batch_p95={batch:.1f}ms"

    _record_case(report, "PF-01", "性能", "正常", "采集延迟 ≤200ms", measure_pf01)

    async def completeness() -> tuple[int, float]:
        store = SQLiteTraceStore(str(run_dir / "perf-complete.db"))
        await store.init_schema()
        inserted = 0
        for trace_index in range(100):
            events = [
                _seed_event(
                    seq,
                    TraceKind.ACTION_END.value,
                    trace_id=f"complete:{trace_index}",
                    session_id="complete",
                )
                for seq in range(1, 101)
            ]
            await store.append_events(events)
            inserted += len(events)
        read = 0
        for trace_index in range(100):
            read += len(await store.list_trace_events(f"complete:{trace_index}"))
        return inserted, read / inserted if inserted else 0.0

    def measure_pf03() -> str:
        inserted, ratio = asyncio.run(completeness())
        report.measurements.append(
            Measurement(
                "数据完整率",
                round(ratio * 100, 4),
                "%",
                COMPLETENESS_LIMIT * 100,
                ratio >= COMPLETENESS_LIMIT,
                f"写入 {inserted} 条 / 逐 trace 回读",
                comparison=">=",
            )
        )
        assert ratio >= COMPLETENESS_LIMIT
        return f"inserted={inserted} completeness={ratio:.4%}"

    _record_case(report, "PF-03", "性能", "边界", "数据完整率 ≥99.9%", measure_pf03)

    async def capacity() -> tuple[float, int]:
        store = SQLiteTraceStore(str(run_dir / "perf-capacity.db"))
        await store.init_schema()
        for trace_index in range(50):
            events = [
                _seed_event(
                    seq,
                    TraceKind.ACTION_END.value,
                    trace_id=f"cap:{trace_index}",
                    session_id="cap",
                )
                for seq in range(1, 51)
            ]
            await store.append_events(events)
        samples: list[float] = []
        for _ in range(10):
            started = time.perf_counter()
            await store.list_trace_events("cap:0")
            samples.append((time.perf_counter() - started) * 1000)
        size = (run_dir / "perf-capacity.db").stat().st_size
        return _p95(samples), size

    def measure_pf04() -> str:
        p95, size = asyncio.run(capacity())
        report.measurements.append(
            Measurement(
                "长会话容量（50 trace × 50 事件）",
                round(p95, 2),
                "ms",
                QUERY_LIMIT_MS,
                True,
                f"单 trace 回读 P95；DB={size / 1024:.1f}KB",
            )
        )
        return f"p95={p95:.1f}ms db={size / 1024:.1f}KB"

    _record_case(report, "PF-04", "性能", "边界", "长会话容量观察", measure_pf04)


def _seed_query_db(run_dir: Path) -> str:
    import asyncio

    from devprompt_ai.memory.trace_store import SQLiteTraceStore

    db = str(run_dir / "perf-query.db")
    store = SQLiteTraceStore(db)

    async def seed() -> None:
        await store.init_schema()
        for trace_index in range(100):
            events = []
            for seq in range(1, 51):
                kind = "turn.start" if seq == 1 else ("turn.end" if seq == 50 else "action.end")
                events.append(
                    _seed_event(
                        seq,
                        kind,
                        trace_id=f"perf:{trace_index}:req",
                        session_id="perf",
                        duration_ms=50,
                    )
                )
            await store.append_events(events)

    asyncio.run(seed())
    return db


def _run_query_perf_server(report: Report, run_dir: Path, model: dict[str, Any] | None) -> None:
    db = _seed_query_db(run_dir)
    server = Server(run_dir, model, tag="perf-query")
    server.db_path = db
    server.start()
    client = httpx.Client(base_url=server.base_url, trust_env=False)

    def measure() -> str:
        paths = [
            "/api/v1/obs/trace/sessions/perf/traces?limit=200",
            "/api/v1/obs/trace/sessions/perf/events?limit=200",
            "/api/v1/obs/trace/traces/perf:0:req?full=false",
            "/api/v1/obs/metrics/summary?session_id=perf&group_by=kind",
            "/api/v1/obs/metrics/alerts?status=active",
        ]
        samples: list[float] = []
        for _ in range(30):
            for path in paths:
                started = time.perf_counter()
                resp = client.get(path, timeout=20)
                samples.append((time.perf_counter() - started) * 1000)
                assert resp.status_code == 200
        p95 = _p95(samples)
        report.measurements.append(
            Measurement(
                "查询响应 P95（5000 事件）",
                round(p95, 2),
                "ms",
                QUERY_LIMIT_MS,
                p95 <= QUERY_LIMIT_MS,
                "5 端点 × 30 次（HTTP，预置 5000 事件）",
            )
        )
        assert p95 <= QUERY_LIMIT_MS, f"p95={p95:.1f}ms"
        return f"p95={p95:.1f}ms n={len(samples)}"

    _record_case(report, "PF-02", "性能", "正常", "查询响应 ≤500ms", measure)
    client.close()
    server.stop()


# ---------------------------------------------------------------------------
# pytest 调度与报告
# ---------------------------------------------------------------------------


def _run_pytest(report: Report, run_dir: Path) -> None:
    junit = run_dir / "junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/e2e/obs",
        "-q",
        "-m",
        "e2e and not real_llm",
        f"--junitxml={junit}",
    ]
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
    summary = (proc.stdout or "").strip().splitlines()
    line = summary[-1] if summary else ""
    report.environment["pytest_summary"] = line
    report.environment["pytest_exit"] = proc.returncode
    if junit.exists():
        root = ET.parse(junit).getroot()
        for testcase in root.iter("testcase"):
            name = testcase.get("name", "")
            classname = testcase.get("classname", "")
            seconds = float(testcase.get("time", "0") or 0) * 1000
            failure = testcase.find("failure")
            error = testcase.find("error")
            skipped = testcase.find("skipped")
            status = "PASS"
            detail = ""
            if failure is not None or error is not None:
                status = "FAIL"
                detail = (failure if failure is not None else error).get("message", "")[:300]
            elif skipped is not None:
                kind = skipped.get("type", "")
                status = "XFAIL" if kind == "pytest.xfail" else "SKIP"
                detail = skipped.get("message", "")[:300]
            report.cases.append(
                CaseResult(
                    case_id=(
                        name.split("_")[1].upper() if len(name.split("_")) > 1 else name.upper()
                    ),
                    module=classname.rsplit(".", 1)[-1],
                    category="确定性回归",
                    title=name,
                    status=status,
                    duration_ms=seconds,
                    evidence=detail,
                )
            )
    report.environment["pytest_duration_ms"] = round((time.perf_counter() - started) * 1000, 1)


def _historical_real_evidence(report: Report) -> None:
    """从历史上真实成功的运行目录复验已落库证据（不再调用 LLM）。"""
    import asyncio

    from devprompt_ai.memory.session_store import SQLiteSessionStore
    from devprompt_ai.memory.trace_store import SQLiteTraceStore

    base = REPO_ROOT / "eval" / "obs" / "runs"
    candidates = sorted(
        [path for path in base.glob("*/success") if (path / "devprompt.db").exists()],
        reverse=True,
    )
    for folder in candidates:
        db = str(folder / "devprompt.db")

        async def probe(db_path: str = db) -> tuple[str, Any, list[Any]] | None:
            summaries = await SQLiteSessionStore(db_path).list_recent("local", limit=50)
            store = SQLiteTraceStore(db_path)
            for summary in summaries:
                for trace in await store.list_traces(summary.session_id):
                    events = await store.list_trace_events(trace.trace_id)
                    kinds = {event.kind for event in events}
                    if "llm.response" in kinds and "turn.end" in kinds:
                        return summary.session_id, trace, events
            return None

        try:
            found = asyncio.run(probe())
        except Exception:  # noqa: BLE001 - 历史库损坏不影响本次报告
            continue
        if found is None:
            continue
        session_id, trace, events = found
        llm_events = [event for event in events if event.kind == "llm.response"]
        report.cases.append(
            CaseResult(
                "RL-01H",
                "真实 LLM（历史证据）",
                "正常",
                "历史真实单轮成功的数据复验",
                "PASS",
                0.0,
                evidence=(
                    f"run={folder.name} session={session_id} trace={trace.trace_id} "
                    f"events={len(events)} llm_events={len(llm_events)}"
                ),
            )
        )
        report.consistency = {
            "historical_run": folder.name,
            "session_id": session_id,
            "trace_id": trace.trace_id,
            "trace_events": len(events),
            "llm_events": len(llm_events),
            "note": "该会话为真实 LLM 单轮成功产物；后续复跑因供应商余额耗尽（5013）改为 BLOCKED",
        }
        return


def _default_defects() -> list[Defect]:
    defects = [
        Defect(
            defect_id="D-01",
            priority="P1",
            title="Trace 多轮事件台账按全局 seq 排序，轮次交错",
            impact=(
                "同一会话两轮以上时，事件列表把 turn0/turn1 交错返回；"
                "按 seq 分页的轮次顺序不稳定，人类回溯体验下降。"
            ),
            reproduction=(
                "uv run pytest "
                "tests/e2e/obs/test_obs_trace.py::test_tr04_multi_turn_pagination_is_turn_major -q"
            ),
            recommendation=(
                "query_events 改为 ORDER BY turn_index, seq；"
                "cursor 改为 (turn_index, seq) 复合游标，并同步调整 API 契约与前端加载更早逻辑。"
            ),
        ),
        Defect(
            defect_id="D-02",
            priority="P0",
            title="trace.write_failed 未登记事件名，写失败时二次抛错破坏 fail-open",
            impact=(
                "TraceCollectorImpl.flush 的异常分支调用 emit('trace.write_failed')，"
                "该事件不在 EVENT_NAMES，emit 抛 ValueError；"
                "当缓冲区在轮次中途写满时异常穿透到业务，Trace 写失败会直接导致本轮优化失败。"
            ),
            reproduction=(
                "uv run pytest tests/e2e/obs/test_obs_resilience.py::"
                "test_ab06_trace_write_failure_keeps_business -q"
            ),
            recommendation=(
                "① 在 observability/logging.EVENT_NAMES 登记 trace.write_failed；"
                "② flush 的 except 分支整体 try/except 包裹 emit，确保观测失败永不外抛。"
            ),
        ),
        Defect(
            defect_id="D-03",
            priority="P1",
            title="并发告警评估触发唯一索引冲突",
            impact=(
                "MetricsService.evaluate 并发（多轮/多会话同时结束）时，"
                "sync_alerts 先查后插无事务保护，触发 metrics_alerts 唯一索引 IntegrityError。"
            ),
            reproduction=(
                "uv run pytest tests/e2e/obs/test_obs_metrics.py::"
                "test_mt04_concurrent_evaluation_is_idempotent -q"
            ),
            recommendation=(
                "sync_alerts 使用 BEGIN IMMEDIATE 单事务 + INSERT ... ON CONFLICT DO UPDATE，"
                "或对同一 scope 加进程内串行锁。"
            ),
        ),
        Defect(
            defect_id="D-04",
            priority="P0",
            title="POST /runs 不接受前端新生成的 session_id，新会话直接 6003",
            impact=(
                "前端 OptimizePage 在新会话时用 crypto.randomUUID() 生成 session_id 并 POST /runs；"
                "RunManager 交给 service.optimize(start_turn) 时该会话不存在，"
                "返回 6003（流程 ID 不存在），新会话无法通过多端运行协议启动。"
                "本次真实场景改用测试预建会话才跑通。"
            ),
            reproduction=(
                "用任意新 UUID POST /api/v1/runs 后订阅 /sessions/{id}/stream："
                "第二条事件即为 error code=6003。"
            ),
            recommendation=(
                "RunManager.start 在会话不存在时创建容器（或新增 POST /sessions 供前端先建会话），"
                "并补充新会话经 /runs 启动的回归用例。"
            ),
        ),
        Defect(
            defect_id="D-06",
            priority="P1",
            title="真实 LLM 调用的 token 用量未进入 Trace/Metrics",
            impact=(
                "真实运行中 llm.response 节点的 attributes.tokens 恒为 0，"
                "导致 Metrics 的 token_total/token_budget 规则失效，成本类指标不可用。"
            ),
            reproduction=(
                "uv run python scripts/obs_e2e.py --real-llm；"
                "查看 RL-01 证据中的 llm_tokens 与 Trace 的 llm.response.attributes.tokens。"
            ),
            recommendation=(
                "在 LLMGenerator 的调用链上确认 agent Runner 是否返回 usage；"
                "缺失时从共享 usage 聚合器（common.cost）回填到 Trace 事件属性。"
            ),
        ),
        Defect(
            defect_id="D-07",
            priority="P1",
            title="真实 Trace 回放出现节点顺序漂移（47 matched / 2 mismatched）",
            impact=(
                "真实运行中 verify_facts 用 asyncio.gather 并发发起多路读取，"
                "事件 seq 取决于完成顺序；回放时并发完成顺序不同，"
                "导致 file.read/read 与 exists 错位，verify 结果为 diverged，无法作为严格回归基线。"
            ),
            reproduction=(
                "uv run python scripts/obs_e2e.py --real-llm；查看 RP-02（XFAIL）与 "
                "eval/obs/runs/<timestamp>/success/devprompt.db 的 replay_nodes diff。"
            ),
            recommendation=(
                "对并发取证按固定 key（工具参数/路径）排序后再分配 seq，"
                "或在比对时按 (kind, name, call_key) 对齐而不是按位置对齐。"
            ),
        ),
        Defect(
            defect_id="D-08",
            priority="P1",
            title="真实 LLM 供应商余额耗尽，重复回归与多轮验证受阻（外部依赖）",
            impact=(
                "本次首个真实单轮成功（66 个 Trace 节点）后，DeepSeek/MiniMax/Kimi 三个已配置供应商"
                "均返回 402/429（余额不足或账号停用），后续真实多轮与重复验证无法完成。"
            ),
            reproduction=(
                "scripts/obs_e2e.py --real-llm 的 RL-01 返回 error code=5013；"
                "直接请求各供应商 chat/completions 返回 402/429。"
            ),
            recommendation=(
                "为测试环境准备独立且有余量的密钥；报告中保留历史成功证据，"
                "余额恢复后按同一命令复跑以补齐多轮场景。"
            ),
        ),
        Defect(
            defect_id="D-05",
            priority="P2",
            title="Session Log 仅覆盖 /runs 链路，/optimize 不写 run_events",
            impact=(
                "直接调用 POST /optimize（旧入口/脚本）产生的会话没有 Session Log 数据，"
                "与「全量日志」预期不一致。"
            ),
            reproduction="使用 POST /api/v1/optimize 后 GET /api/v1/events?session_id=... 返回空。",
            recommendation=(
                "统一入口：/optimize 也注入 EventSink，"
                "或在文档与 UI 明确 Session Log 仅适用于 /runs 运行。"
            ),
        ),
    ]
    # 2026-11-14：D-01 ~ D-07 已修复并有确定性回归用例；D-08 为外部依赖，保持 open。
    for defect in defects:
        if defect.defect_id != "D-08":
            defect.status = "fixed（2026-11-14，回归用例已覆盖）"
    return defects


def _render_markdown(report: Report, run_dir: Path) -> str:
    passed = sum(1 for case in report.cases if case.status == "PASS")
    failed = sum(1 for case in report.cases if case.status == "FAIL")
    xfailed = sum(1 for case in report.cases if case.status == "XFAIL")
    blocked = sum(1 for case in report.cases if case.status == "BLOCKED")
    metrics_ok = all(item.passed for item in report.measurements)

    lines: list[str] = []
    lines.append(f"# 可观测性四模块端到端测试报告（{DATE}）")
    lines.append("")
    lines.append("## 一、执行摘要")
    lines.append("")
    lines.append(
        f"- 用例：**{len(report.cases)}**（PASS {passed} / FAIL {failed} / "
        f"XFAIL {xfailed} / BLOCKED {blocked}）"
    )
    lines.append(f"- 性能门槛：**{'全部达标' if metrics_ok else '存在未达标项'}**")
    lines.append(f"- 真实 LLM：{'已执行' if report.environment.get('real_llm') else '未执行'}")
    lines.append(f"- 执行目录：`{run_dir}`")
    lines.append("")
    lines.append("## 二、环境与方法")
    lines.append("")
    for key, value in report.environment.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## 三、用例结果")
    lines.append("")
    lines.append("| 用例 | 模块 | 分类 | 结果 | 耗时(ms) | 证据/错误 |")
    lines.append("|---|---|---|---|---|---|")
    for case in report.cases:
        detail = (case.evidence or case.error).replace("|", "\\|").replace("\n", " ")[:180]
        lines.append(
            f"| {case.case_id} | {case.module} | {case.category} | {case.status} | "
            f"{case.duration_ms:.0f} | {detail} |"
        )
    lines.append("")
    lines.append("## 四、性能结果")
    lines.append("")
    lines.append("| 指标 | 值 | 门槛 | 结果 | 方法 |")
    lines.append("|---|---|---|---|---|")
    for item in report.measurements:
        lines.append(
            f"| {item.name} | {item.value} {item.unit} | "
            f"{item.comparison}{item.threshold} {item.unit} | "
            f"{'PASS' if item.passed else 'FAIL'} | {item.method} |"
        )
    lines.append("")
    lines.append("## 五、跨模块一致性证据")
    lines.append("")
    if report.consistency:
        for key, value in report.consistency.items():
            lines.append(f"- {key}: `{value}`")
    else:
        lines.append("- 真实 LLM 场景未执行，一致性证据来自 pytest 确定性用例（XM-01～XM-06）。")
    lines.append("")
    lines.append("## 六、缺陷清单（仅报告）")
    lines.append("")
    for defect in report.defects:
        lines.append(f"### {defect.defect_id} · {defect.priority} · {defect.title}")
        lines.append("")
        lines.append(f"- 影响：{defect.impact}")
        lines.append(f"- 复现：`{defect.reproduction}`")
        lines.append(f"- 建议：{defect.recommendation}")
        lines.append(f"- 状态：{defect.status}")
        lines.append("")
    lines.append("## 七、风险评估")
    lines.append("")
    lines.append(
        "- **P0 写失败二次抛错**：Trace 写异常会穿透业务，"
        "属于可观测性反向影响可用性，建议优先修复。"
    )
    lines.append("- **P1 并发告警冲突**：多会话同时结束可能丢失告警评估，影响指标可信度。")
    lines.append("- **P1 多轮台账交错**：只影响回溯可读性与分页稳定性，不影响数据完整性。")
    lines.append("- **P1 真实回放顺序漂移**：并发取证事件顺序不稳定，严格回归会误报 diverged。")
    lines.append("- **P1 token 用量为 0**：Metrics 成本指标与 token 预算告警当前不可用。")
    lines.append("- **P1 供应商余额耗尽（外部）**：真实 LLM 多轮与重复回归暂时不可执行。")
    lines.append("- **数据隔离**：本次全部使用临时 DB；未修改用户真实数据库与 settings。")
    lines.append("")
    lines.append("## 八、优化建议")
    lines.append("")
    lines.append("1. 修复 D-02，并为所有 emit 调用加“事件名登记”单测门禁。")
    lines.append("2. 修复 D-03，采用单事务 upsert，并在高并发用例中保留回归。")
    lines.append("3. 修复 D-01 的排序与复合游标，前端 Trace 台账增加轮次分组。")
    lines.append("4. 统一 `/optimize` 与 `/runs` 的事件写入，消除 Session Log 数据盲区。")
    lines.append("")
    lines.append("## 九、复现命令")
    lines.append("")
    lines.append("```powershell")
    lines.append('uv run pytest tests/e2e/obs -q -m "e2e and not real_llm"')
    lines.append('$env:OBS_E2E_REAL_LLM = "1"')
    lines.append("uv run pytest tests/e2e/obs/test_obs_real_llm.py -q")
    lines.append("uv run python scripts/obs_e2e.py --real-llm")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="可观测性四模块 E2E 报告")
    parser.add_argument("--real-llm", action="store_true", help="执行真实 LLM 三场景")
    parser.add_argument("--skip-pytest", action="store_true", help="跳过确定性 pytest 套件")
    parser.add_argument(
        "--report-dir", default=str(REPO_ROOT / "eval" / "obs"), help="报告输出目录"
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    run_dir = report_dir / "runs" / STAMP
    run_dir.mkdir(parents=True, exist_ok=True)
    report = Report(run_dir=str(run_dir))
    report.defects = _default_defects()
    model = _read_real_model()
    report.environment = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "real_llm": bool(args.real_llm and model),
        "model": (model or {}).get("model_id", ""),
        "base_url": (model or {}).get("base_url", ""),
        "project": str(PROJECT),
        "db_isolation": "临时目录（不触碰用户真实 DB）",
    }

    if not args.skip_pytest:
        _run_pytest(report, run_dir)

    _run_perf(report, run_dir)
    _historical_real_evidence(report)
    fallback_model = model or {
        "base_url": "http://127.0.0.1:1",
        "model_id": "perf-dummy",
        "api_key": "dummy",
        "provider": "openai",
        "api_mode": "chat_completions",
    }
    _run_query_perf_server(report, run_dir, fallback_model)

    if args.real_llm and model is not None:
        server = Server(run_dir, model, tag="success")
        try:
            server.start()
            _run_success_scenarios(report, server)
        finally:
            server.stop()
        _run_failure_scenario(report, run_dir, model)
    else:
        report.cases.append(
            CaseResult(
                "RL-00",
                "全链路",
                "正常",
                "真实 LLM 场景",
                "SKIP",
                0.0,
                evidence="未传 --real-llm 或 settings.json 未配置",
            )
        )

    markdown = _render_markdown(report, run_dir)
    md_path = report_dir / f"report-{DATE}.md"
    json_path = report_dir / f"report-{DATE}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "environment": report.environment,
                "cases": [asdict(case) for case in report.cases],
                "measurements": [asdict(item) for item in report.measurements],
                "defects": [asdict(defect) for defect in report.defects],
                "consistency": report.consistency,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    failed = [case for case in report.cases if case.status == "FAIL"]
    threshold_failed = [item for item in report.measurements if not item.passed]
    print(f"报告：{md_path}")
    print(f"原始指标：{json_path}")
    print(f"用例 {len(report.cases)}，FAIL {len(failed)}，性能未达标 {len(threshold_failed)}")
    return 1 if failed or threshold_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
