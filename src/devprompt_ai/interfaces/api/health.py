"""环境自检（原 CLI doctor 检查项平移）：rg/ctags/git 版本、DB 文件可写、llm 配置非空。

探测通道统一走 common.process.run_command（MUST-13）；SQLite 会话库探测以
「DB 文件可写」替代——api 层禁 import memory 实现模块（Web 薄壳约束）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from devprompt_ai.common.process import run_command
from devprompt_ai.config import AppConfig
from devprompt_ai.interfaces.api.schemas import HealthCheckItem, HealthResponse


def _probe_db_writable(db_path: str) -> str:
    """DB 文件可写探测（同步 I/O，经 to_thread 卸载，MUST-13）。"""
    db = Path(db_path).expanduser()
    db.parent.mkdir(parents=True, exist_ok=True)
    with open(db, "a", encoding="utf-8"):
        pass
    return str(db)


async def run_checks(cfg: AppConfig) -> HealthResponse:
    """逐项探测并聚合；单项失败不中断其余检查（与原 doctor 行为一致）。"""
    checks: list[HealthCheckItem] = [
        HealthCheckItem(
            name="llm_config",
            ok=bool(cfg.llm_base_url and cfg.llm_model),
            detail=f"{cfg.llm_base_url} / {cfg.llm_model}",
        )
    ]
    for tool in ("rg", "ctags", "git"):
        try:
            out = await run_command([tool, "--version"], timeout=5.0)
            checks.append(HealthCheckItem(name=tool, ok=True, detail=out.splitlines()[0][:60]))
        except Exception as exc:  # 自检需逐项报告而非中断（原 doctor 同语义）
            checks.append(HealthCheckItem(name=tool, ok=False, detail=repr(exc)[:80]))
    try:
        detail = await asyncio.to_thread(_probe_db_writable, cfg.db_path)
        checks.append(HealthCheckItem(name="db_writable", ok=True, detail=detail))
    except OSError as exc:
        checks.append(HealthCheckItem(name="db_writable", ok=False, detail=repr(exc)[:80]))
    return HealthResponse(checks=checks, is_healthy=all(c.ok for c in checks))
