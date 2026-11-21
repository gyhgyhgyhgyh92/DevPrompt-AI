#!/usr/bin/env python3
"""Smoke-check the packaged sidecar (cross-platform).

Replaces smoke-sidecar.ps1, which was Windows-only (Start-Process -WindowStyle,
taskkill, Invoke-WebRequest -UseBasicParsing -- the last flag was removed in
PowerShell 7 and errors out on POSIX).

Checks:
  1. launch the built sidecar with the bundled toolchain injected
  2. read the DPROMPT_READY line from stdout and parse the port
  3. GET /api/v1/health -> healthy, and rg / ctags / llm_config all ok
  4. GET / -> frontend served (200)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "desktop"
SIDECAR_DIST = DESKTOP_DIR / "dist" / "sidecar-dist"

READY_PREFIX = "DPROMPT_READY"
READY_TIMEOUT_SEC = 30.0
IS_WINDOWS = sys.platform == "win32"


def tool_filename(name: str) -> str:
    """Executable file name: .exe suffix on Windows, none on POSIX."""
    return f"{name}.exe" if IS_WINDOWS else name


def sidecar_exe() -> Path:
    """Path of the PyInstaller one-dir sidecar binary."""
    return SIDECAR_DIST / "devprompt-ai-desktop" / tool_filename("devprompt-ai-desktop")


def http_get(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    """GET a URL, returning (status, body); HTTP errors are returned, not raised."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def wait_ready(process: subprocess.Popen[str], deadline: float) -> int:
    """Read stdout until the ready line appears; return the advertised port."""
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            line = line.strip()
            if line.startswith(READY_PREFIX):
                payload = json.loads(line[len(READY_PREFIX) :].strip())
                port = int(payload["port"])
                if port <= 0:
                    raise SystemExit(f"invalid port in ready protocol: {port}")
                return port
            raise SystemExit(f"stdout polluted before ready line: {line!r}")
        if process.poll() is not None:
            raise SystemExit(f"sidecar exited early with code {process.returncode}")
        time.sleep(0.1)
    raise SystemExit(f"sidecar not ready within {READY_TIMEOUT_SEC:.0f}s")


def stop(process: subprocess.Popen[str]) -> None:
    """Terminate the sidecar: kill the group on POSIX, the tree on Windows."""
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/pid", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()


def main() -> int:
    """Run the smoke check against the built sidecar."""
    exe = sidecar_exe()
    if not exe.exists():
        raise SystemExit(f"sidecar binary missing: {exe}")

    tools_dir = SIDECAR_DIST / "tools"
    env = dict(os.environ)
    env["DEVPROMPT_FRONTEND_DIST"] = str(REPO_ROOT / "frontend" / "dist")
    for tool in ("rg", "ctags"):
        candidate = tools_dir / tool_filename(tool)
        if candidate.exists():
            env[f"DPROMPT_{tool.upper()}_PATH"] = str(candidate)

    process = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=not IS_WINDOWS,
    )
    try:
        port = wait_ready(process, time.monotonic() + READY_TIMEOUT_SEC)

        status, body = http_get(f"http://127.0.0.1:{port}/api/v1/health")
        if status != 200:
            raise SystemExit(f"health endpoint returned {status}: {body[:400]!r}")
        # 响应契约：{"code":0,"message":"ok","data":{"checks":[{name,ok,detail}],"is_healthy":bool}}
        payload = json.loads(body)
        data = payload.get("data", {})
        if not data.get("is_healthy"):
            raise SystemExit(f"service reports unhealthy: {body[:400]!r}")
        checks = {item["name"]: item for item in data.get("checks", [])}
        for key in ("rg", "ctags", "llm_config"):
            item = checks.get(key)
            if item is None:
                raise SystemExit(f"health check {key} missing from response")
            if not item.get("ok"):
                raise SystemExit(f"health check {key} failed: {item.get('detail')!r}")

        status, _ = http_get(f"http://127.0.0.1:{port}/")
        if status != 200:
            raise SystemExit(f"frontend root returned {status}")

        print(f"==> smoke ok: sidecar on port {port}, rg/ctags/llm_config all ok")
        return 0
    finally:
        stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
