"""动作观测层测试：卡片内容、脱敏、噪音抑制与旁路失败（MUST-19）。"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai.domain.progress import ActionInfo, ProgressEvent
from devprompt_ai.harness.trace import TracingReader, TracingRunner, redact

_ROOT = "D:/proj"


class FakeSink:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[ActionInfo]:
        return [e.action for e in self.events if e.action is not None]


class ExplodingSink:
    async def emit(self, _event: ProgressEvent) -> None:
        raise RuntimeError("sink down")


class FakeRunner:
    def __init__(self, out: str = "", fail: Exception | None = None) -> None:
        self.out = out
        self.fail = fail
        self.calls: list[list[str]] = []

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        self.calls.append(args)
        if self.fail is not None:
            raise self.fail
        return self.out


class FakeReader:
    def __init__(self, text: str = "", exists: bool = True) -> None:
        self.text = text
        self._exists = exists
        self.reads: list[str] = []
        self.exist_calls: list[str] = []

    async def read(self, path: str) -> str:
        self.reads.append(path)
        return self.text

    async def exists(self, path: str) -> bool:
        self.exist_calls.append(path)
        return self._exists


def test_redact_strips_root_and_drive_prefixes() -> None:
    assert redact("D:/proj/src/ui/Button.tsx", _ROOT) == "src/ui/Button.tsx"
    assert redact(r"D:\proj\src\ui\Button.tsx", _ROOT) == "src/ui/Button.tsx"
    # 非本项目的绝对路径：收窄为末两段，不整条外泄
    assert redact("C:/Users/hzt/secret/file.ts", _ROOT) == "secret/file.ts"


async def test_runner_reports_card_without_route_key() -> None:
    sink = FakeSink()
    runner = TracingRunner(FakeRunner("a.ts:1:x\nb.ts:2:y\n"), sink, _ROOT)

    await runner.run(
        [
            "rg",
            "--fixed-strings",
            "-n",
            "Foo",
            "--glob",
            "src/a.ts",
            ".",
            "--route-key=symbol:src/a.ts",
        ]
    )

    assert len(sink.actions()) == 1
    action = sink.actions()[0]
    assert action.title == "检索符号"
    assert action.scope == "命中 2 行"
    assert "route-key" not in action.detail
    assert "Foo" in action.detail


async def test_no_match_still_reports_card() -> None:
    """rg 无匹配（exit 1）是有效信息，不是错误：仍出卡片并标「无匹配」。"""
    sink = FakeSink()
    runner = TracingRunner(FakeRunner(""), sink, _ROOT)

    await runner.run(
        ["rg", "-n", "data-testid", "--glob", "src/a.tsx", ".", "--route-key=testid:src/a.tsx"]
    )

    assert sink.actions()[0].scope == "无匹配"
    assert sink.actions()[0].title == "检查测试锚点"


async def test_reader_reports_relative_path_and_line_range() -> None:
    sink = FakeSink()
    reader = TracingReader(FakeReader("line1\nline2\nline3\n"), sink, _ROOT)

    await reader.read("D:/proj/src/ui/Button.tsx")

    action = sink.actions()[0]
    assert action.title == "读取文件"
    assert action.detail == "src/ui/Button.tsx"
    assert action.scope == "L1-3"


async def test_exists_is_not_reported() -> None:
    """一次取证做 5 次存在性检查，逐条上报只会刷噪音卡。"""
    sink = FakeSink()
    reader = TracingReader(FakeReader(), sink, _ROOT)

    assert await reader.exists("D:/proj/src/ui/Button.tsx") is True
    assert sink.actions() == []


async def test_observation_failure_never_breaks_call() -> None:
    runner = TracingRunner(FakeRunner("hit\n"), ExplodingSink(), _ROOT)
    assert await runner.run(["rg", "x"]) == "hit\n"

    reader = TracingReader(FakeReader("a"), ExplodingSink(), _ROOT)
    assert await reader.read("D:/proj/a.ts") == "a"


async def test_inner_failure_propagates_unchanged() -> None:
    sink = FakeSink()
    runner = TracingRunner(FakeRunner(fail=RuntimeError("boom")), sink, _ROOT)

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run(["rg", "x"])
    assert sink.events == []


def test_action_detail_never_leaks_root() -> None:
    """卡片载荷里不得出现 root 绝对路径（MUST-19 的结构性断言）。"""
    args: list[Any] = ["rg", "--glob", "D:/proj/src/a.ts", "."]
    detail = redact(" ".join(str(a) for a in args), _ROOT)
    assert "D:/proj" not in detail


class TestOutputCapture:
    """动作输出：复用 lines、脱敏、20 行 / 2000 字符截断（2026-10-22）。"""

    async def test_output_truncated_to_twenty_lines(self) -> None:
        sink = FakeSink()
        runner = TracingRunner(
            FakeRunner("\n".join(f"line{i}" for i in range(30)) + "\n"), sink, _ROOT
        )

        await runner.run(["rg", "x"])

        output = sink.actions()[0].output
        assert "…（已截断）" in output
        assert "line0" in output
        assert "line29" not in output
        assert len(output.splitlines()) <= 21

    async def test_output_redacts_absolute_paths(self) -> None:
        sink = FakeSink()
        runner = TracingRunner(FakeRunner("hit D:/proj/src/a.ts\n"), sink, _ROOT)

        await runner.run(["rg", "x"])

        output = sink.actions()[0].output
        assert "D:/proj" not in output
        assert "src/a.ts" in output

    async def test_empty_output_stays_empty(self) -> None:
        sink = FakeSink()
        runner = TracingRunner(FakeRunner(""), sink, _ROOT)

        await runner.run(["rg", "x"])

        assert sink.actions()[0].output == ""

    async def test_reader_reports_content_head(self) -> None:
        sink = FakeSink()
        reader = TracingReader(FakeReader("a\nb\nc\n"), sink, _ROOT)

        await reader.read("D:/proj/src/a.ts")

        assert sink.actions()[0].output == "a\nb\nc"
