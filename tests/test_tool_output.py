"""工具输出治理测试：阈值、摘要、落盘、注册表、晚到闸门与批处理。"""

from __future__ import annotations

import time
from pathlib import Path

from devprompt_ai.harness.output_store import cleanup, persist, raw_path, read
from devprompt_ai.harness.output_summary import (
    summarize_output,
    threshold_for,
    with_footer,
)
from devprompt_ai.harness.tool_batch import BatchItem, merge_results, plan_batches
from devprompt_ai.harness.tool_registry import (
    LateRegistrationGate,
    ToolRegistry,
    normalize_name,
)


def test_threshold_depends_on_semantic_density() -> None:
    assert threshold_for("read_file", min_chars=1000) == 2000
    assert threshold_for("grep", min_chars=1000) == 670
    assert threshold_for("unknown", min_chars=1000) == 1000


def test_success_keeps_tail_only() -> None:
    text = "\n".join(f"line{i}" for i in range(100))

    summary = summarize_output(text, success=True, success_lines=5)

    assert summary.splitlines() == [f"line{i}" for i in range(95, 100)]


def test_failure_keeps_error_anchor_and_tail() -> None:
    lines = [f"line{i}" for i in range(100)]
    lines[50] = "Error: boom"

    summary = summarize_output("\n".join(lines), success=False)
    body = summary.splitlines()

    assert any("Error: boom" in line for line in body)
    assert "…（中间省略）…" in body
    assert body[-1] == "line99"


def test_short_output_is_untouched() -> None:
    text = "a\nb\nc"

    assert summarize_output(text, success=False) == text


def test_footer_warns_not_to_rerun() -> None:
    assert "不要重跑命令" in with_footer("body", "/tmp/x.raw")
    assert "read_file /tmp/x.raw" in with_footer("body", "/tmp/x.raw")
    assert "不要重跑命令" in with_footer("body", "")


async def test_output_store_roundtrip_and_cleanup() -> None:
    path = await persist("call-1", "全量输出")

    assert await read(path) == "全量输出"
    assert path.endswith(".raw")
    assert await read(str(Path(path).with_suffix(".missing"))) is None

    old = time.time() - 7200
    import asyncio
    import os

    assert await asyncio.to_thread(os.path.exists, path)
    await asyncio.to_thread(os.utime, path, (old, old))
    assert cleanup(older_than_s=3600) >= 1
    assert raw_path("call-1").name.endswith(".raw")


def test_registry_alias_and_overwrite() -> None:
    registry: ToolRegistry[str] = ToolRegistry()

    assert normalize_name("task") == "delegate_task"
    assert registry.register("task", "first") is False
    assert registry.get("delegate_task") == "first"
    assert registry.register("delegate_task", "second") is True
    assert registry.overwritten() == frozenset({"delegate_task"})


def test_registry_presets() -> None:
    registry: ToolRegistry[str] = ToolRegistry()
    for name in ("read_file", "grep", "write_file"):
        registry.register(name, name)

    assert registry.names("minimal") == ["grep", "read_file"]
    assert registry.names("full") == ["grep", "read_file", "write_file"]


async def test_late_registration_gate() -> None:
    gate = LateRegistrationGate(timeout_s=0.05)
    assert await gate.wait() is True

    gate.begin()
    assert gate.pending == 1
    assert await gate.wait() is False, "超时放行但不阻断"

    gate.end()
    assert await gate.wait() is True


def test_batch_planning_and_order() -> None:
    items = [
        BatchItem(0, "grep", True),
        BatchItem(1, "read_file", True),
        BatchItem(2, "write_file", False),
        BatchItem(3, "grep", True),
    ]

    batches = plan_batches(items)
    assert [[item.index for item in batch] for batch in batches] == [[0, 1], [2], [3]]

    merged = merge_results(batches, ["r0", "r1", "r2", "r3"])
    assert merged == ["r0", "r1", "r2", "r3"]
