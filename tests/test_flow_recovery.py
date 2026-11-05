"""F-804 流程恢复一致性测试：两条取快照路径逐项对照（同一 mock 决策层 + 固定种子）。

对照对象为同一 flow_id 的两种获取方式：
① HTTP 路径——流程推进端点（``POST /optimize`` / ``POST /followup``）返回的「实时」快照；
② resume 重复获取路径——**同一 flow_id** 经 ``GET /progress/{flow_id}`` SSE 中断（读首事件即停）
   后改由 ``GET /result/{flow_id}`` 重建，以及反问经 ``POST /followup/{flow_id}`` 后再拉快照。

断言（F-804 验收）：
① 三套方案正文逐套 diff 为空；
② ranking 视图 fit/total/confidence/gap/marked/reason 六字段逐字段相等。

F-804 豁免：决策层与生成器输出均为**确定性 fake**（不调用真实 LLM），故结果可复现。
本文件仅测试，不改动生产代码；fake 严格按 Protocol 签名实现（MUST-06 单向依赖）。
"""

from __future__ import annotations

import difflib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import httpx
import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.decision.port import (
    AskQuestion,
    FactJudgment,
    FactProbeOutput,
    RankComponentsOutput,
    ScorePromptsOutput,
    VariantScore,
)
from devprompt_ai.domain.generate.ports import (
    GenerationContext,
    Level,
    MultiVariantDraft,
    VariantDraft,
)
from devprompt_ai.domain.models import (
    Candidate,
    FactResult,
    FlowSession,
    SessionSummary,
    Symbol,
)
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.interfaces.api import routes
from devprompt_ai.interfaces.api.app import create_app
from devprompt_ai.service import _RANK_CACHE, ForgeService

# F-804 ②：ranking 视图需逐字段对照的七字段（variant 不在比对项内）。
_RANKING_FIELDS: tuple[str, ...] = (
    "fit",
    "total",
    "confidence",
    "gap",
    "marked",
    "reason",
)

_SENTENCE = "把提交按钮改成 primary-500"


# ---- 最小 test doubles（严格按 Protocol 签名，全部确定性、零真实 I/O） ----


@dataclass
class FakeStore:
    """SessionStore 最小内存实现（乐观锁语义：save 自增 version 并恒成功）。"""

    items: dict[str, FlowSession] = field(default_factory=dict)

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[SessionSummary]:
        return []

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        return 0  # 本用例不覆盖项目级删除（详见 test_session_store.py）


class FixedDecider:
    """DecisionPort 确定性实现：rank 恒等序、probe/score 固定值（固定种子）。"""

    def __init__(
        self,
        confs: list[float] | None = None,
        scores: dict[str, tuple[int, float]] | None = None,
    ) -> None:
        self.confs = confs if confs is not None else [0.9] * 7
        self.scores = (
            scores if scores is not None else {"A": (2, 0.9), "B": (3, 0.9), "C": (4, 0.9)}
        )

    async def rank_components(
        self, sentence: str, candidates: list[Candidate]
    ) -> RankComponentsOutput:
        return RankComponentsOutput(order=list(range(len(candidates))), confidence=0.9)

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        keys = [f.key for f in facts]
        judgments = [
            FactJudgment(key=k, passed=c >= 0.75, confidence=c)
            for k, c in zip(keys, self.confs, strict=False)
        ]
        # 反问时机由决策层给出（2026-10-20）：只对真实缺口提问，等价旧行为
        gaps = [
            j.key for j, f in zip(judgments, facts, strict=False) if not (f.passed and j.passed)
        ]
        return FactProbeOutput(
            judgments=judgments,
            overall_confidence=sum(self.confs) / len(self.confs) if self.confs else 0.0,
            questions=[AskQuestion(key=k, question=f"请确认 {k}") for k in gaps],
        )

    async def score_prompts(
        self, context: str, variants: list[tuple[str, str]]
    ) -> ScorePromptsOutput:
        return ScorePromptsOutput(
            scores=[
                VariantScore(
                    variant=cast(Literal["A", "B", "C"], key),
                    score=self.scores[key][0],
                    confidence=self.scores[key][1],
                )
                for key, _ in variants
            ]
        )


class FixedGenerator:
    """GeneratePort 确定性实现：正文随档位/序号固定生成（供 diff 对照）。"""

    async def generate_single(self, ctx: GenerationContext) -> VariantDraft:
        return VariantDraft(title="t", body=f"body-{ctx.level}", changes=["x"], level=ctx.level)

    async def generate_variants(
        self, ctx: GenerationContext, levels: list[Level]
    ) -> MultiVariantDraft:
        return MultiVariantDraft(
            variants=[
                VariantDraft(
                    title=f"方案{level}",
                    body=f"方案正文-{level}-{idx}",
                    changes=[f"变更-{idx}"],
                    level=level,
                )
                for idx, level in enumerate(levels)
            ]
        )

    async def answer(self, ctx: GenerationContext) -> str:
        return "回答"


class FakeRunner:
    """CommandRunner 最小实现：按 rg 参数中的 token 路由（内容确定性）。"""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str]] = [
            ("SubmitButton", "src/ui/button.tsx:12:SubmitButton"),
            ("--color-x", "src/styles/tokens.css:1:  --color-x: #3b82f6"),
            ("data-testid", "src/ui/button.tsx:14:  data-testid='s'"),
            (":hover", "src/ui/button.tsx:20:  .btn:hover"),
        ]

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        for needle, out in self.routes:
            if any(needle in a for a in args[2:]):
                return out
        return ""


class FakeReader:
    """FileReader 最小实现：给定存在集 + 固定文本（含选择器/ token / data-testid）。"""

    def __init__(self, existing: set[str]) -> None:
        self.existing = existing

    async def read(self, path: str) -> str:
        return (
            "export function SubmitButton() { return <button data-testid='s' "
            "class='btn btn:hover'/> } /* --color-x */"
        )

    async def exists(self, path: str) -> bool:
        return path in self.existing


def _symbols() -> list[Symbol]:
    """冻结 F-102 的 MIN_CANDIDATES=3：三符号保证非 manual（同分时名字更短优先）。"""
    return [
        Symbol(name="SubmitButton", path="src/ui/button.tsx", line=12, kind="function"),
        Symbol(name="SubmitButtonGroup", path="src/ui/button_group.tsx", line=30, kind="function"),
        Symbol(name="SubmitForm", path="src/ui/form.tsx", line=8, kind="function"),
    ]


def _service(existing: set[str] | None = None) -> ForgeService:
    """组装确定性 ForgeService（复用 service.build_default 之外的显式注入路径）。"""
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    return ForgeService(
        cfg=cfg,
        decider=FixedDecider(),
        sessions=FakeStore(),
        runner=FakeRunner(),
        reader=FakeReader(existing if existing is not None else {"src/ui/button.tsx"}),
        generator=FixedGenerator(),
        symbols_provider=SymbolTableProvider(FakeRunner(), ttl_seconds=0.0),
        symbols_override=_symbols(),
    )


@pytest.fixture(autouse=True)
def _isolated_rank_cache() -> None:
    """模块级 rank 缓存按用例隔离（MUST-14），避免跨用例污染。"""
    _RANK_CACHE.clear()


@asynccontextmanager
async def _client(
    monkeypatch: pytest.MonkeyPatch, existing: set[str] | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """注入确定性 ForgeService（routes.get_service），经 ASGI 内存传输驱动真实路由。"""
    svc = _service(existing)

    async def _fake_get_service() -> ForgeService:
        return svc

    monkeypatch.setattr(routes, "get_service", _fake_get_service)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _first_sse_event(client: httpx.AsyncClient, flow_id: str) -> dict[str, Any]:
    """读取 SSE 首事件即退出 ``async with`` → 等价「SSE 中断后改由 GET /result 取快照」。"""
    async with client.stream("GET", f"/api/v1/progress/{flow_id}") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                return cast(dict[str, Any], json.loads(line[len("data: ") :]))
    raise AssertionError("SSE 未产出任何事件")


def _assert_recovery_consistent(live: dict[str, Any], recovered: dict[str, Any]) -> None:
    """F-804 ①②：两路径快照逐项对照（不一致即失败，不得静默）。"""
    # ① 三套方案正文逐套 diff 为空（先校档位集合，再逐套 diff）
    live_variants = cast(list[dict[str, Any]], live["variants"])
    rec_variants = cast(list[dict[str, Any]], recovered["variants"])
    assert [v["level"] for v in live_variants] == [v["level"] for v in rec_variants], (
        f"档位集合不一致：{live_variants} vs {rec_variants}"
    )
    for left, right in zip(live_variants, rec_variants, strict=True):
        diff = list(difflib.unified_diff(left["body"].splitlines(), right["body"].splitlines()))
        assert diff == [], f"方案 {left['level']} 正文 diff 非空：{diff}"

    # ② ranking 视图七字段逐字段相等
    live_rank = live["ranking"]
    rec_rank = recovered["ranking"]
    assert (live_rank is None) == (rec_rank is None), (
        f"ranking 有无不一致：{live_rank} vs {rec_rank}"
    )
    if live_rank is not None and rec_rank is not None:
        for name in _RANKING_FIELDS:
            assert live_rank[name] == rec_rank[name], (
                f"ranking.{name} 不一致：{live_rank[name]} != {rec_rank[name]}"
            )


# ---- 用例：resume 重复执行路径 vs HTTP 实时路径 ----


async def test_followup_recovery_consistency(monkeypatch: pytest.MonkeyPatch) -> None:
    """ASK→followup→DONE 全链：optimize/followup 实时快照与 SSE 中断后 GET /result 重建快照一致。"""
    async with _client(monkeypatch) as client:
        # 路径①：POST /optimize 起流程（实时快照，ASKING）
        resp = await client.post("/api/v1/optimize", json={"sentence": _SENTENCE, "project": "."})
        assert resp.status_code == 200
        live_ask = resp.json()["data"]
        flow_id = live_ask["session_id"]
        assert live_ask["status"] == "ask"
        assert [q["key"] for q in live_ask["questions"]] == ["请确认 test_file_exists"]

        # 路径②：SSE 中断 → GET /result 重建（ASKING 阶段对照）
        await _first_sse_event(client, flow_id)
        recovered_ask = (await client.get(f"/api/v1/result/{flow_id}")).json()["data"]
        _assert_recovery_consistent(live_ask, recovered_ask)
        assert live_ask == recovered_ask  # 同会话只读重建应完全一致

        # 路径①：POST /followup 批量答复推进至 DONE（实时快照，含方案与 ranking）
        resp = await client.post(
            f"/api/v1/followup/{flow_id}",
            json={"answers": {"请确认 test_file_exists": "新增 src/ui/button.test.tsx"}},
        )
        assert resp.status_code == 200
        live_done = resp.json()["data"]
        assert live_done["status"] == "done"
        assert live_done["ranking"] is not None  # B 档路径：A/B 两套 → 打分与推荐判定

        # 路径②：SSE 中断 → GET /result 重建（DONE 阶段对照）
        done_event = await _first_sse_event(client, flow_id)
        assert done_event["state"] == "DONE"
        recovered_done = (await client.get(f"/api/v1/result/{flow_id}")).json()["data"]
        _assert_recovery_consistent(live_done, recovered_done)
        assert live_done == recovered_done


async def test_clean_flow_recovery_consistency(monkeypatch: pytest.MonkeyPatch) -> None:
    """七项全过（C 档三套）：optimize 实时快照与 SSE 中断后 GET /result 重建快照一致。"""
    existing = {"src/ui/button.tsx", "src/ui/button.test.tsx"}
    async with _client(monkeypatch, existing) as client:
        resp = await client.post("/api/v1/optimize", json={"sentence": _SENTENCE, "project": "."})
        assert resp.status_code == 200
        live = resp.json()["data"]
        flow_id = live["session_id"]
        assert live["status"] == "done"  # 零提问（MUST-26 ①）
        assert [v["level"] for v in live["variants"]] == ["A", "B", "C"]  # 三套同调
        assert live["ranking"] is not None

        recovered = (await client.get(f"/api/v1/result/{flow_id}")).json()["data"]
        _assert_recovery_consistent(live, recovered)
        assert live == recovered
