"""领域包端到端流程测试（Fake 注入）：通用域无项目直交付、白名单、越权兜底。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.agent.action import AgentAction, AgentStep
from devprompt_ai.domain.decision.port import FactProbeOutput, NextActionOutput
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.domain.generate.ports import GenerationContext, VariantDraft
from devprompt_ai.domain.models import FactResult, FlowSession
from devprompt_ai.harness.process import SymbolTableProvider
from devprompt_ai.service import ForgeService

_GENERIC_BODY = (
    "## 一、目标与背景\n写周报。\n## 二、任务拆解\n分三步。\n"
    "## 三、规范与约束\nMarkdown。\n## 四、交付标准\n可直接粘贴。"
)


class DomainGenerator:
    def __init__(self) -> None:
        self.last_ctx: GenerationContext | None = None

    async def generate_single(  # type: ignore[no-untyped-def]
        self, ctx, locale="zh-CN", *, fallback: bool = False
    ):
        self.last_ctx = ctx
        body = _GENERIC_BODY if ctx.domain_id != "code" else "b"
        return VariantDraft(title="t", body=body, changes=["周报正文"], fallback=fallback)

    async def answer(self, ctx, locale="zh-CN"):  # type: ignore[no-untyped-def]
        return "回答"


class _NoPlannerDecider:
    """只实现 DecisionPort 前三类、不实现 next_action -> optimize 走 linear。"""

    async def rank_components(self, sentence: str, candidates: list[Any]) -> object:
        raise AssertionError("通用域不应触发排序")

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        # generate 动作内部会研判（信息不足转反问）；空判定=不拦
        return FactProbeOutput(judgments=[], overall_confidence=0.9)

    async def score_prompts(self, sentence: str, variants: list[Any]) -> object:
        raise AssertionError("通用域不应触发打分")


class _FakeRunner:
    async def run(self, args: list[str], **kw: object) -> str:
        return ""


class _FakeReader:
    async def read(self, path: str) -> str:
        return "line\n" * 30

    async def exists(self, path: str) -> bool:
        return False


@dataclass(slots=True)
class FakeStore:
    """SessionStore 内存桩：方法集与 tests/test_service.py 的 FakeStore 对齐。"""

    items: dict[str, FlowSession] = field(default_factory=dict)

    async def create(self, session: FlowSession) -> None:
        self.items[session.session_id] = session

    async def load(self, session_id: str) -> FlowSession | None:
        return self.items.get(session_id)

    async def save(self, session: FlowSession) -> bool:
        session.version += 1
        self.items[session.session_id] = session
        return True

    async def list_recent(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[Any]:
        return []

    async def delete(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None

    async def delete_by_project(self, user_id: str, project_root: str) -> int:
        return 0


def _service(generator: object) -> ForgeService:
    return ForgeService(
        cfg=AppConfig(_env_file=None),  # type: ignore[call-arg]
        decider=_NoPlannerDecider(),  # type: ignore[arg-type]
        sessions=FakeStore(),
        runner=_FakeRunner(),
        reader=_FakeReader(),
        generator=generator,  # type: ignore[arg-type]
        symbols_provider=SymbolTableProvider(_FakeRunner(), ttl_seconds=0.0),
    )


def _session_of(svc: ForgeService) -> FlowSession:
    store = cast(FakeStore, svc._sessions)  # noqa: SLF001
    return next(iter(store.items.values()))


async def test_generic_flow_without_project_delivers() -> None:
    gen = DomainGenerator()
    svc = _service(gen)
    snapshot = await svc.optimize("local", "", "帮我写个周报，重点写数据结果", request_id="r1")
    session = _session_of(svc)
    assert session.data["domain"]["domain"] == "work"
    assert session.data["domain"]["source"] == "keyword"
    assert gen.last_ctx is not None and gen.last_ctx.domain_id == "work"
    assert snapshot.state == "DONE"
    assert session.data["delivery_gate"]["status"] == "GREEN"


async def test_structural_failure_discloses_red() -> None:
    class BadGenerator(DomainGenerator):
        async def generate_single(self, ctx, locale="zh-CN", *, fallback=False):  # type: ignore[no-untyped-def]
            self.last_ctx = ctx
            return VariantDraft(title="t", body="随便写的正文", changes=[], fallback=fallback)

    svc = _service(BadGenerator())
    await svc.optimize("local", "", "帮我写个周报", request_id="r2")
    gate = _session_of(svc).data["delivery_gate"]
    assert gate["status"] == "RED"
    assert gate["tone"] == "error"


async def test_code_keyword_without_project_rejected() -> None:
    svc = _service(DomainGenerator())
    with pytest.raises(DevPromptError) as exc:
        await svc.optimize("local", "", "帮我重构这个函数", request_id="r3")
    assert exc.value.code == 2001
    assert "项目路径" in str(exc.value)


async def test_unknown_override_rejected() -> None:
    svc = _service(DomainGenerator())
    with pytest.raises(DevPromptError) as exc:
        await svc.optimize("local", "", "随便写点什么", request_id="r4", domain_override="nonsense")
    assert exc.value.code == 1002


async def test_override_beats_keyword() -> None:
    gen = DomainGenerator()
    svc = _service(gen)
    await svc.optimize("local", "", "帮我做一份计划", request_id="r5", domain_override="life")
    session = _session_of(svc)
    assert session.data["domain"]["domain"] == "life"
    assert session.data["domain"]["source"] == "override"


@dataclass(slots=True)
class ScriptedPlanner:
    """最小 planner mock：按脚本回放动作，记录收到的白名单。"""

    actions: list[AgentAction]
    calls: int = 0
    allowed_sets: list[frozenset[str] | None] = field(default_factory=list)

    async def next_action(
        self,
        *,
        sentence: str,
        facts: Sequence[FactResult],
        steps: Sequence[AgentStep],
        variant_count: int,
        clarifications: Mapping[str, str],
        correction: str = "",
        inherited_variant_count: int = 0,
        allowed_actions: Sequence[AgentAction] | None = None,
    ) -> NextActionOutput:
        self.allowed_sets.append(
            frozenset(a.value for a in allowed_actions) if allowed_actions else None
        )
        action = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        return NextActionOutput(
            action=action.value, reason="脚本", confidence=0.9, confidence_source="measured"
        )

    async def probe_facts(
        self,
        sentence: str,
        facts: list[FactResult],
        *,
        answered: Mapping[str, str] | None = None,
    ) -> FactProbeOutput:
        return FactProbeOutput(judgments=[], overall_confidence=0.9)

    async def rank_components(self, sentence: str, candidates: list[Any]) -> object:
        raise AssertionError("不应触发排序")

    async def score_prompts(self, sentence: str, variants: list[Any]) -> object:
        raise AssertionError("不应触发打分")


def _planner_service(planner: ScriptedPlanner, generator: object) -> ForgeService:
    svc = _service(generator)
    svc._planner = planner  # noqa: SLF001
    return svc


async def test_generic_domain_planner_whitelist() -> None:
    planner = ScriptedPlanner(actions=[AgentAction.GENERATE, AgentAction.DELIVER])
    svc = _planner_service(planner, DomainGenerator())
    await svc.optimize("local", "", "帮我写个周报", request_id="r6")
    assert planner.allowed_sets
    allowed = planner.allowed_sets[0]
    assert allowed is not None
    assert not allowed & {"retrieve", "probe", "delegate"}
    assert {"generate", "deliver", "ask"} <= allowed


async def test_out_of_whitelist_action_downgrades_to_generate() -> None:
    gen = DomainGenerator()
    planner = ScriptedPlanner(actions=[AgentAction.RETRIEVE, AgentAction.DELIVER])
    svc = _planner_service(planner, gen)
    snapshot = await svc.optimize("local", "", "帮我写个周报", request_id="r7")
    assert gen.last_ctx is not None and gen.last_ctx.domain_id == "work"
    assert snapshot.state == "DONE"
    assert _session_of(svc).data["delivery_gate"]["status"]
