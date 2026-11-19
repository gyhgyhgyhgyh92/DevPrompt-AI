"""轻量级真实服务端到端夹具：真起 uvicorn 子进程、随机端口、临时库与临时设置。

设计要点：
- 子进程环境变量覆盖 `DB_PATH` / `DEVPROMPT_SETTINGS_FILE`，绝不碰用户真实库与设置；
- 随机空闲端口避免与本地 8000 冲突；
- 就绪探测用 `/api/v1/health`，超时直接杀进程并带出日志，避免挂死 CI；
- 退出时 terminate → 等待 → kill，Windows 下也不留僵尸进程。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
READY_TIMEOUT_S = 60.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LiveServer:
    def __init__(self, *, base_url: str, data_dir: Path, process: subprocess.Popen[str]) -> None:
        self.base_url = base_url
        self.data_dir = data_dir
        self.process = process
        self.client = httpx.Client(base_url=base_url, timeout=30.0)

    def close(self) -> None:
        self.client.close()


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiveServer]:
    data_dir = tmp_path_factory.mktemp("live-e2e")
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "DB_PATH": str(data_dir / "live.db"),
            "DEVPROMPT_SETTINGS_FILE": str(data_dir / "settings.json"),
            "APP_ENV": "test",
            # 子进程日志不写用户目录
            "LOG_DIR": str(data_dir / "logs"),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "devprompt_ai.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + READY_TIMEOUT_S
    ready = False
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"服务进程提前退出（code={process.returncode}）：\n{output[-4000:]}")
        try:
            response = httpx.get(f"{base_url}/api/v1/health", timeout=1.5)
            if response.status_code == 200:
                ready = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    if not ready:
        process.kill()
        output = process.stdout.read() if process.stdout else ""
        raise RuntimeError(f"服务在 {READY_TIMEOUT_S}s 内未就绪：\n{output[-4000:]}")

    server = LiveServer(base_url=base_url, data_dir=data_dir, process=process)
    try:
        yield server
    finally:
        server.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def api(live_server: LiveServer) -> Iterator[httpx.Client]:
    yield live_server.client


def envelope(response: httpx.Response) -> dict[str, Any]:
    """拆统一响应信封；契约不符直接失败，避免测试静默通过。"""
    payload = response.json()
    assert isinstance(payload, dict) and "code" in payload, payload
    return payload


@pytest.fixture(scope="session")
def tiny_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tiny-project")
    (root / "app.py").write_text(
        "def submit_button():\n    return 'old'\n\n\ndef cancel_button():\n    return 'cancel'\n",
        encoding="utf-8",
    )
    return root
