"""环境自检（原 CLI doctor 检查项平移）：rg/ctags/git 版本、DB 文件可写、llm 配置非空。

探测通道统一走 common.process.run_command（MUST-13）；SQLite 会话库探测以
「DB 文件可写」替代——api 层禁 import memory 实现模块（Web 薄壳约束）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from devprompt_ai.common.envhint import render_env_hint
from devprompt_ai.common.health_probe import probe_service
from devprompt_ai.common.process import run_command
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.startup_report import ACTION_FAILED, latest_report
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
    llm_missing = cfg.llm_problems()
    if llm_missing:
        llm_detail = render_env_hint(llm_missing)
        llm_ok = False
    else:
        llm_detail = f"{cfg.llm_base_url} / {cfg.llm_model}"
        llm_ok = True
    checks: list[HealthCheckItem] = [
        HealthCheckItem(name="llm_config", ok=llm_ok, detail=llm_detail)
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
    # N-1 启动自愈报告（报告类型在 domain，此处只读——薄壳禁 import memory，MUST-06）
    repair = latest_report()
    checks.append(
        HealthCheckItem(
            name="storage_repair",
            ok=repair.action != ACTION_FAILED,
            detail=repair.summary(),
        )
    )
    # 自进化侧车（2026-11-22）：未启用时恒绿（不装扮成故障），启用后按实际连通性报告。
    if cfg.reflection_enabled:
        reflection_ok, reflection_detail = await probe_service(
            cfg.reflection_base_url, cfg.reflection_secret_path, "/agentmemory/health"
        )
    else:
        # 稳定标记（非自然语言）：前端据此区分「未启用」与「已连接」，文案由前端 i18n 决定
        reflection_ok, reflection_detail = True, "disabled"
    checks.append(HealthCheckItem(name="reflection", ok=reflection_ok, detail=reflection_detail))
    return HealthResponse(checks=checks, is_healthy=all(c.ok for c in checks))
