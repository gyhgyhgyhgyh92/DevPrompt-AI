#!/usr/bin/env python3
"""Cross-platform desktop build orchestration (Windows / macOS / Linux).

Replaces build-desktop.ps1 + build-sidecar.ps1: both were PowerShell and
Windows-only (backslash literals, WinGet dirs, taskkill, Inno Setup iscc).
Three platforms would mean two sets of shell logic. PyInstaller cannot cross
compile, so the sidecar must be built natively per platform -- CI matrix
covers that.

Pipeline:
  1. build frontend (frontend/dist)
  2. compile Electron shell (desktop/dist/main.js, preload.js)
  3. PyInstaller sidecar (one-dir, console=True)
  4. collect rg / ctags into sidecar-dist/tools/
  5. run electron-builder to produce the installer

Step 4 mirrors the resolution chain in src/devprompt_ai/common/process.py:
PATH -> common install dirs -> DPROMPT_<NAME>_PATH env var.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "desktop"
DIST = DESKTOP_DIR / "dist"
SIDECAR_DIST = DIST / "sidecar-dist"
TOOLS_DIR = SIDECAR_DIST / "tools"

IS_WINDOWS = sys.platform == "win32"
TOOLS = ("rg", "ctags")

INSTALL_HINTS = {
    "win32": {
        "rg": "winget install BurntSushi.ripgrep.MSVC",
        "ctags": "winget install universal-ctags.ctags",
    },
    "darwin": {
        "rg": "brew install ripgrep",
        "ctags": "brew install universal-ctags",
    },
    "linux": {
        "rg": "apt install ripgrep",
        "ctags": "apt install universal-ctags",
    },
}


def run(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command; a non-zero exit aborts the pipeline (no half-built output).

    The executable is resolved through shutil.which: on Windows `pnpm` is a
    `.cmd` shim, which subprocess cannot launch without the extension.
    """
    exe = shutil.which(cmd[0])
    if exe is None:
        raise SystemExit(f"command not found: {cmd[0]}")
    resolved = [exe, *cmd[1:]]
    print(f"  $ {' '.join(resolved)}", flush=True)
    subprocess.run(resolved, cwd=str(cwd or REPO_ROOT), check=True)


def tool_filename(name: str) -> str:
    """Executable file name: .exe suffix on Windows, none on POSIX."""
    return f"{name}.exe" if IS_WINDOWS else name


def candidate_dirs() -> list[Path]:
    """Common tool install dirs (a GUI app's PATH usually omits these)."""
    dirs: list[Path] = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            dirs.append(Path(local) / "Microsoft" / "WinGet" / "Links")
            dirs.append(Path(local) / "Programs")
    else:
        dirs.extend(
            [
                Path("/opt/homebrew/bin"),
                Path("/opt/homebrew/sbin"),
                Path("/usr/local/bin"),
                Path("/usr/bin"),
                Path("/bin"),
                Path.home() / ".cargo" / "bin",
                Path.home() / ".local" / "bin",
            ]
        )
    return [d for d in dirs if d.is_dir()]


def resolve_tool(name: str) -> Path | None:
    """Locate a tool binary: PATH -> common install dirs -> explicit env var."""
    found = shutil.which(name)
    if found:
        return Path(found)
    filename = tool_filename(name)
    for base in candidate_dirs():
        candidate = base / filename
        if candidate.is_file():
            return candidate
    env_val = os.environ.get(f"DPROMPT_{name.upper()}_PATH")
    if env_val and Path(env_val).is_file():
        return Path(env_val)
    return None


def build_frontend() -> None:
    print("==> [1/5] build frontend", flush=True)
    run(["pnpm", "-C", str(REPO_ROOT / "frontend"), "build"])


def build_shell() -> None:
    print("==> [2/5] compile Electron shell", flush=True)
    run(["pnpm", "-C", str(DESKTOP_DIR), "build"])


def build_sidecar() -> None:
    print("==> [3/5] PyInstaller sidecar (one-dir)", flush=True)
    run(
        [
            "uv",
            "run",
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(SIDECAR_DIST),
            "--workpath",
            str(REPO_ROOT / ".tmp" / "pyinstaller-work"),
            str(DESKTOP_DIR / "pyinstaller" / "sidecar.spec"),
        ]
    )
    exe = SIDECAR_DIST / "devprompt-ai-desktop" / tool_filename("devprompt-ai-desktop")
    if not exe.exists():
        raise SystemExit(f"PyInstaller output missing: {exe}")


def collect_tools() -> None:
    print("==> [4/5] collect rg / ctags", flush=True)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    hints = INSTALL_HINTS.get(sys.platform, INSTALL_HINTS["linux"])
    for tool in TOOLS:
        src = resolve_tool(tool)
        if src is None:
            raise SystemExit(
                f"tool not found: {tool}. The installer must ship the search "
                f"toolchain or desktop symbol lookup is unusable.\n"
                f"install: {hints[tool]}\n"
                f"or set DPROMPT_{tool.upper()}_PATH to its full path and retry."
            )
        dst = TOOLS_DIR / tool_filename(tool)
        shutil.copy2(src, dst)
        print(f"  collected {tool} <- {src}", flush=True)


def build_installer() -> None:
    print("==> [5/5] electron-builder", flush=True)
    run(["pnpm", "-C", str(DESKTOP_DIR), "dist"])


def main() -> int:
    build_frontend()
    build_shell()
    build_sidecar()
    collect_tools()
    build_installer()
    print("==> desktop build done:", DIST / "packages", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
