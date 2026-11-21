"""桌面端 sidecar 入口测试（2026-10-22 桌面化）。

锁死的契约：
1. 端口由内核分配且 socket 已 listen，直传 uvicorn（无「先报端口后 bind」竞态）；
2. stdout 只有单行 ``DPROMPT_READY`` 协议——uvicorn access 日志必须改道 stderr；
3. ``DEVPROMPT_FRONTEND_DIST`` 可重定位前端产物（Electron 注入，壳侧契约）；
4. 入口模块保持薄壳：无模块级 devprompt_ai import、无业务常量（同 main.py 不变量）。
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from devprompt_ai import desktop


class TestBindEphemeralSocket:
    def test_binds_listening_loopback_socket(self) -> None:
        sock = desktop.bind_ephemeral_socket()
        try:
            host, port = sock.getsockname()
            assert host == "127.0.0.1"
            assert 0 < port < 65536
            # 已 listen：uvicorn 可直接 create_server(sock=sock)，无需再 bind
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
        finally:
            sock.close()

    def test_port_is_kernel_assigned_not_fixed(self) -> None:
        """两次绑定必须拿到不同端口——写死端口会与 Web 版 8000 或彼此冲突。"""
        first = desktop.bind_ephemeral_socket()
        try:
            second = desktop.bind_ephemeral_socket()
            try:
                assert first.getsockname() != second.getsockname()
            finally:
                second.close()
        finally:
            first.close()


class TestReadyProtocol:
    def test_ready_line_is_single_json_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        desktop._emit_ready(43117)
        assert capsys.readouterr().out == 'DPROMPT_READY {"port":43117}\n'

    def test_ready_line_is_machine_parseable(self, capsys: pytest.CaptureFixture[str]) -> None:
        """主进程按「前缀 + 单行 JSON」解析，键名与分隔符不能漂移。"""
        desktop._emit_ready(8080)
        prefix, payload = capsys.readouterr().out.strip().split(" ", 1)
        assert prefix == desktop.READY_LINE_PREFIX
        assert json.loads(payload) == {"port": 8080}


class TestAccessLogOnStderr:
    def test_access_log_redirected_to_stderr(self) -> None:
        """access 日志默认落 stdout，会污染协议流，必须显式改道。"""
        cfg = desktop._stderr_access_log_config()
        assert cfg["handlers"]["access"]["stream"] == "ext://sys.stderr"

    def test_uvicorn_own_logs_stay_on_stderr(self) -> None:
        cfg = desktop._stderr_access_log_config()
        assert cfg["handlers"]["default"]["stream"] == "ext://sys.stderr"

    def test_does_not_mutate_uvicorn_global_config(self) -> None:
        """deepcopy 改副本：其他进程（Web 形态）还要用原配置。"""
        import uvicorn.config

        before = uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"]
        desktop._stderr_access_log_config()
        assert uvicorn.config.LOGGING_CONFIG["handlers"]["access"]["stream"] == before


class TestMainWiring:
    def test_random_port_socket_passed_to_uvicorn(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import uvicorn

        captured: dict[str, Any] = {}

        class _FakeServer:
            def __init__(self, config: uvicorn.Config) -> None:
                captured["config"] = config

            def run(self, sockets: list[socket.socket] | None = None) -> None:
                captured["sockets"] = sockets

        monkeypatch.setattr(uvicorn, "Server", _FakeServer)

        assert desktop.main() == 0

        socks = captured["sockets"]
        assert isinstance(socks, list) and len(socks) == 1
        host, port = socks[0].getsockname()
        try:
            assert host == "127.0.0.1"
            assert 0 < port < 65536
            assert captured["config"].host == "127.0.0.1"
            # ready 行的端口必须与真正交给 uvicorn 的 socket 端口一致
            assert capsys.readouterr().out == f'DPROMPT_READY {{"port":{port}}}\n'
        finally:
            socks[0].close()


class TestFrontendDistOverride:
    def test_env_override_relocates_dist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Electron 经 DEVPROMPT_FRONTEND_DIST 注入安装目录内的产物路径。"""
        from devprompt_ai.interfaces.api import app as app_module

        dist = tmp_path / "frontend-dist"
        dist.mkdir()
        monkeypatch.setenv("DEVPROMPT_FRONTEND_DIST", str(dist))
        assert app_module._frontend_dist() == dist


class TestEntryModulePurity:
    """入口模块薄壳不变量（与 test_main_entry.py 对 main.py 的要求相同）。"""

    def _source(self) -> str:
        return (Path(__file__).resolve().parents[1] / "src/devprompt_ai/desktop.py").read_text(
            encoding="utf-8"
        )

    def test_no_module_level_devprompt_imports(self) -> None:
        module_level = [
            line
            for line in self._source().splitlines()
            if line.startswith(("import ", "from ")) and "devprompt_ai" in line
        ]
        assert module_level == []

    def test_no_business_constants(self) -> None:
        for forbidden in ("0.12", "0.6", "0.4", "threshold", "score", "weight"):
            assert forbidden not in self._source(), f"入口层出现业务常量：{forbidden}"

    def test_console_script_registered(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        assert 'devprompt-ai-desktop = "devprompt_ai.desktop:main"' in source
