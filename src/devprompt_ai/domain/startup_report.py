"""启动自愈报告（N-1）：纯数据 + 进程级状态，供 memory 写入、health 读取。

为什么需要独立的领域模块：MUST-06 禁止 `interfaces/api/health.py` import `memory/`，
但 `PRAGMA integrity_check` 是 SQL、只能在 `memory/` 执行——形成闭环约束。
把报告的**类型与状态**放在 `domain/`，两侧都只做「基础设施/表现层 → 领域」
方向的导入，约束即解开。

状态是**进程级单值**：本项目是单进程本地 Web 服务（架构文档 §1.1），应用启动时
写入一次、`/health` 只读，不存在多副本不一致问题。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: 修复动作分类（供 /health 的 storage_repair 项展示与前端分色）
ACTION_OK = "ok"
ACTION_REPAIRED = "repaired"
ACTION_QUARANTINED = "quarantined"
ACTION_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StartupRepairReport:
    """一次启动自愈的结果。

    ⚠️ **不得**把损坏行的原始内容写入本报告——它可能含用户原句（MUST-19）。
    本报告只记录计数与分类，`issues` 里只放可安全展示的描述。
    """

    action: str = ACTION_OK
    repaired: tuple[str, ...] = ()
    quarantined: int = 0
    issues: tuple[str, ...] = ()
    checked_at: float = field(default_factory=time.time)

    @property
    def is_ok(self) -> bool:
        return self.action == ACTION_OK

    def summary(self) -> str:
        """一行摘要（不含任何用户数据）。"""
        if self.is_ok:
            return "存储结构完整，无需修复"
        parts: list[str] = []
        if self.repaired:
            parts.append(f"已补建 {len(self.repaired)} 项")
        if self.quarantined:
            parts.append(f"已隔离 {self.quarantined} 行损坏数据")
        if self.issues:
            parts.append(f"{len(self.issues)} 项异常")
        return "；".join(parts)


#: 进程级最近一次报告（模块内私有，外部只能经读写函数访问）
_LAST_REPORT: StartupRepairReport | None = None


def record_report(report: StartupRepairReport) -> None:
    """记录本次启动自愈结果（由 `memory/` 在检查后调用）。"""
    global _LAST_REPORT  # noqa: PLW0603 - 进程级单值存储，刻意如此
    _LAST_REPORT = report


def latest_report() -> StartupRepairReport:
    """读取最近一次报告；未检查过则返回「无需修复」而非 None（简化调用方）。"""
    if _LAST_REPORT is None:
        return StartupRepairReport()
    return _LAST_REPORT


def reset_report() -> None:
    """清空记录（仅供测试隔离用）。"""
    global _LAST_REPORT  # noqa: PLW0603 - 同上
    _LAST_REPORT = None
