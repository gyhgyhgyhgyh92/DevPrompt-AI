"""同轮补充检索工具测试：参数组装、结果裁剪、工具执行与启用条件。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.generate.ports import GenerationContext
from devprompt_ai.domain.retrieval.ports import CommandRunner
from devprompt_ai.domain.retrieval.tool_search import (
    MAX_SEARCH_HITS,
    build_search_args,
    render_hits,
)
from devprompt_ai.harness.llm import LLMGenerator, _search_code_tool


class FakeRunner(CommandRunner):
    """记录 rg 参数，按需返回命中行或抛错。"""

    def __init__(self, output: str = "", error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[list[str], str | None]] = []

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        self.calls.append((list(args), cwd))
        if self.error is not None:
            raise self.error
        return self.output


def test_build_search_args_is_fixed_string() -> None:
    args = build_search_args("SubmitButton")

    assert args[:2] == ["rg", "--fixed-strings"]
    assert "-n" in args
    assert "--max-count" in args
    assert args[args.index("-e") + 1] == "SubmitButton", "检索词按字面传给 -e，不转正则"


def test_render_hits_marks_empty_and_truncates() -> None:
    assert render_hits("") == "（无命中）"
    assert render_hits("\n\n") == "（无命中）"

    many = "\n".join(f"src/a.ts:{i}:hit" for i in range(50))
    rendered = render_hits(many)

    assert len(rendered.splitlines()) == MAX_SEARCH_HITS
    assert rendered.startswith("src/a.ts:0:hit")


async def test_tool_executes_query_and_renders_hits() -> None:
    runner = FakeRunner("src/ui/button.tsx:12:SubmitButton")

    tool = _search_code_tool("D:/repo", runner)
    result = await tool.on_invoke_tool(None, json.dumps({"query": "SubmitButton"}))  # type: ignore[arg-type]

    assert "SubmitButton" in str(result)
    args, cwd = runner.calls[0]
    assert cwd == "D:/repo"
    assert "SubmitButton" in args


async def test_tool_rejects_empty_or_invalid_query() -> None:
    runner = FakeRunner("x")

    tool = _search_code_tool("D:/repo", runner)
    empty = await tool.on_invoke_tool(None, json.dumps({"query": "  "}))  # type: ignore[arg-type]
    broken = await tool.on_invoke_tool(None, "{not json")  # type: ignore[arg-type]

    assert "query" in str(empty)
    assert "query" in str(broken)
    assert runner.calls == [], "参数非法时不得执行外部命令"


async def test_tool_failure_degrades_to_message() -> None:
    runner = FakeRunner(error=RuntimeError("rg exploded"))

    tool = _search_code_tool("D:/repo", runner)
    result = await tool.on_invoke_tool(None, json.dumps({"query": "x"}))  # type: ignore[arg-type]

    assert "检索失败" in str(result), "工具失败不得抛出到生成主链"


async def test_observability_failure_does_not_break_tool(monkeypatch: Any) -> None:
    """事件登记/遥测故障不得中断工具（SDK 会把工具异常包成 UserError 中断整轮）。"""
    from devprompt_ai.harness import llm as llm_module

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("未登记事件名")

    monkeypatch.setattr(llm_module, "emit", _boom)
    runner = FakeRunner("src/a.ts:1:hit")

    tool = _search_code_tool("D:/repo", runner)
    result = await tool.on_invoke_tool(None, json.dumps({"query": "hit"}))  # type: ignore[arg-type]

    assert "hit" in str(result)


def _ctx(domain_id: str = "code") -> GenerationContext:
    return GenerationContext(sentence="改一下", project_root="D:/repo", domain_id=domain_id)


def test_tools_enabled_only_for_code_domain_with_runner() -> None:
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]

    with_runner = LLMGenerator(cfg, runner=FakeRunner())
    without_runner = LLMGenerator(cfg)

    assert len(with_runner._generate_tools(_ctx())) == 1  # noqa: SLF001
    assert with_runner._generate_tools(_ctx(domain_id="work")) == ()  # noqa: SLF001
    assert without_runner._generate_tools(_ctx()) == ()  # noqa: SLF001


def test_tools_disabled_when_turns_is_one() -> None:
    cfg = AppConfig(_env_file=None, generate_tool_turns=1)  # type: ignore[call-arg]

    generator = LLMGenerator(cfg, runner=FakeRunner())

    assert generator._generate_tools(_ctx()) == ()  # noqa: SLF001


async def test_chat_structured_forwards_tools_and_turns(monkeypatch: Any) -> None:
    """工具与轮次预算必须透传到单候选调用（否则 SDK 不会执行工具）。"""
    from devprompt_ai.harness import llm as llm_module

    captured: dict[str, Any] = {}

    async def _fake_once(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(llm_module, "_structured_once", _fake_once)
    monkeypatch.setattr(llm_module, "_resolve_chain", _fake_chain)
    monkeypatch.setattr(llm_module, "_assert_request_budget", lambda *a, **k: None)

    tool = _search_code_tool("D:/repo", FakeRunner())
    await llm_module.chat_structured(
        AppConfig(_env_file=None),  # type: ignore[call-arg]
        _Draft,
        "system",
        "user",
        tools=(tool,),
        max_turns=3,
    )

    assert captured["max_turns"] == 3
    assert len(captured["tools"]) == 1


async def _fake_chain(*_args: Any, **_kwargs: Any) -> list[Any]:
    class _Candidate:
        llm_model = "test-model"
        llm_base_url = "http://local"
        llm_api_key = "k"

        def model_copy(self, **_kw: Any) -> Any:
            return self

    return [_Candidate()]


class _Draft(BaseModel):
    """占位输出模型：只需满足 chat_structured 的 BaseModel 约束。"""
