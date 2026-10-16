"""跨平台编排器测试（N-3）：平台差异集中化与串并行顺序。

借鉴 prompt-optimizer `scripts/run-many.test.mjs` 的元测试思路——编排器自身的
行为本身就是契约，必须被测试，否则重构时会静默改变构建语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from runner import (  # noqa: E402
    DEFAULT_MAX_PARALLEL,
    SHELL_REQUIRED_SUFFIXES,
    RunnerSpec,
    build_argv,
    get_runner_spec,
    parse_args,
    resolve_tool,
    run_many,
    run_step,
)


class TestRunnerSpec:
    def test_windows_uses_comspec_with_d_s_c(self) -> None:
        spec = get_runner_spec("pnpm", platform="win32", env={"ComSpec": r"C:\W\cmd.exe"})
        assert spec.command == r"C:\W\cmd.exe"
        assert spec.prefix == ("/d", "/s", "/c", "pnpm")
        assert spec.shell is False

    def test_windows_falls_back_to_uppercase_comspec(self) -> None:
        """环境变量键名大小写在不同 shell 下不一致，必须双写兜底。"""
        spec = get_runner_spec("pnpm", platform="win32", env={"COMSPEC": "cmd2.exe"})
        assert spec.command == "cmd2.exe"

    def test_windows_defaults_to_cmd_exe(self) -> None:
        spec = get_runner_spec("pnpm", platform="win32", env={})
        assert spec.command == "cmd.exe"

    def test_unix_has_no_prefix(self) -> None:
        spec = get_runner_spec("uv", platform="linux", env={})
        assert spec == RunnerSpec(command="uv", prefix=(), shell=False)


class TestBuildArgv:
    def test_cmd_shell_on_windows_is_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("runner.resolve_tool", lambda t: r"C:\npm\pnpm.CMD")
        argv = build_argv("pnpm build", platform="win32", env={"ComSpec": "cmd.exe"})
        assert argv == ["cmd.exe", "/d", "/s", "/c", r"C:\npm\pnpm.CMD", "build"]

    def test_exe_on_windows_is_not_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`.exe` 可被 Windows 直接执行，多包一层 shell 只会增加风险。"""
        monkeypatch.setattr("runner.resolve_tool", lambda t: r"C:\bin\uv.exe")
        argv = build_argv("uv build", platform="win32", env={})
        assert argv == [r"C:\bin\uv.exe", "build"]

    def test_unix_never_wraps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("runner.resolve_tool", lambda t: "/usr/bin/pnpm")
        argv = build_argv("pnpm build", platform="linux", env={})
        assert argv == ["/usr/bin/pnpm", "build"]

    def test_shell_metacharacters_treated_as_plain_args(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不做 shell 解析：`&` `|` 只是普通参数，不构成注入面。"""
        monkeypatch.setattr("runner.resolve_tool", lambda t: "/usr/bin/echo")
        argv = build_argv("echo a && rm -rf /", platform="linux", env={})
        assert argv == ["/usr/bin/echo", "a", "&&", "rm", "-rf", "/"]

    def test_empty_step_rejected(self) -> None:
        with pytest.raises(ValueError, match="空步骤"):
            build_argv("   ")


class TestResolveTool:
    def test_missing_tool_raises_with_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("runner.shutil.which", lambda _t: None)
        with pytest.raises(FileNotFoundError, match="docs.astral.sh"):
            resolve_tool("uv")

    def test_missing_generic_tool_has_fallback_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("runner.shutil.which", lambda _t: None)
        with pytest.raises(FileNotFoundError, match="PATH"):
            resolve_tool("some-unknown-tool")


class TestRunMany:
    def test_serial_stops_at_first_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_step(step: str, **_kw: object) -> int:
            calls.append(step)
            return 1 if step == "b" else 0

        monkeypatch.setattr("runner.run_step", fake_run_step)
        assert run_many(["a", "b", "c"]) == 1
        assert calls == ["a", "b"], "失败后不得继续执行后续步骤"

    def test_serial_runs_in_declaration_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            "runner.run_step",
            lambda s, **_k: calls.append(s) or 0,  # type: ignore[func-returns-value]
        )
        assert run_many(["x", "y", "z"]) == 0
        assert calls == ["x", "y", "z"]

    def test_empty_steps_is_success(self) -> None:
        assert run_many([]) == 0

    def test_parallel_reports_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_step(step: str, **_kw: object) -> int:
            return 1 if step == "bad" else 0

        monkeypatch.setattr("runner.run_step", fake_run_step)
        assert run_many(["ok1", "bad", "ok2"], parallel=True) == 1

    def test_parallel_propagates_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(step: str, **_kw: object) -> int:
            raise FileNotFoundError("工具缺失")

        monkeypatch.setattr("runner.run_step", boom)
        assert run_many(["a"], parallel=True) == 1

    def test_default_parallel_limit_is_bounded(self) -> None:
        """`uv sync` 很吃 IO，无上限并发会打满磁盘。"""
        assert 1 <= DEFAULT_MAX_PARALLEL <= 4

    def test_dry_run_does_not_execute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`run_step(dry_run=True)` 只打印，不 spawn任何进程（run_many 亦委托于此）。"""

        def forbidden(*_a: object, **_k: object) -> int:
            raise AssertionError("dry-run 不应执行")

        monkeypatch.setattr("runner.subprocess.run", forbidden)
        assert run_step("uv build", dry_run=True) == 0

    def test_dry_run_passes_through_run_many(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_many 必须把 dry_run 透传给每一步（依赖 run_step 自身的短路）。"""
        seen: list[bool] = []
        monkeypatch.setattr(
            "runner.run_step",
            lambda _s, *, dry_run=False, **_k: seen.append(dry_run) or 0,  # type: ignore[func-returns-value]
        )
        run_many(["a", "b"], dry_run=True)
        assert seen == [True, True]


class TestShellSuffixes:
    def test_suffixes_cover_windows_batch_files(self) -> None:
        assert ".cmd" in SHELL_REQUIRED_SUFFIXES
        assert ".bat" in SHELL_REQUIRED_SUFFIXES


class TestParseArgs:
    def test_defaults_are_serial(self) -> None:
        args = parse_args(["uv build"])
        assert args.parallel is False
        assert args.dry_run is False
        assert args.steps == ["uv build"]

    def test_flags_parsed(self) -> None:
        args = parse_args(["-p", "--max-parallel", "4", "--dry-run", "a", "b"])
        assert args.parallel is True
        assert args.max_parallel == 4
        assert args.dry_run is True
        assert args.steps == ["a", "b"]
