"""启动自愈（N-1）：SQLite 结构校验 → 缺表补建 → 坏行隔离。

为什么需要：本地 SQLite 文件可能被外部因素写坏（磁盘异常、强制断电、手工编辑）。
原行为是「启动即崩」或「静默丢数据」。本模块在 `service.build_default()` 构造
Manager 之前先做一次体检：

1. `PRAGMA integrity_check` —— 非 `ok` 时逐表隔离损坏行（**移入 `forge_quarantine`
   而非删除**，本地单用户工具误删不可恢复）；
2. 校验 `memory/schema.py` 声明的表是否齐备 —— 缺表则幂等补建；
3. 产出 `StartupRepairReport` 交给 `domain.startup_report` 记录。

安全边界（MUST-19）：报告只含计数与分类，**不含任何行内容或用户原句**。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from devprompt_ai.domain.startup_report import (
    ACTION_FAILED,
    ACTION_OK,
    ACTION_QUARANTINED,
    ACTION_REPAIRED,
    StartupRepairReport,
    record_report,
)
from devprompt_ai.memory.schema import (
    ARTIFACTS_DDL,
    INTERVENTIONS_DDL,
    ORPHAN_SESSIONS_SQL,
    ORPHAN_TURNS_SQL,
    PROJECT_NOTES_DDL,
    QUARANTINE_DDL,
    REPO_GRAPH_DDL,
    ROUTING_STATS_DDL,
    RUN_EVENTS_DDL,
    RUNS_DDL,
    SESSIONS_DDL,
    SETTINGS_DDL,
    TOKEN_LEDGER_DDL,
    TURNS_DDL,
)
from devprompt_ai.observability.logging import emit

#: 需齐备的业务表 → DDL（顺序即补建顺序）
_REQUIRED_TABLES: tuple[tuple[str, str], ...] = (
    ("forge_sessions", SESSIONS_DDL),
    ("app_settings", SETTINGS_DDL),
    ("forge_quarantine", QUARANTINE_DDL),
    ("forge_turns", TURNS_DDL),
    ("project_notes", PROJECT_NOTES_DDL),
    # 运行时层（2026-11-07）：缺表时同样补建，旧库自动升级
    ("runs", RUNS_DDL),
    ("run_events", RUN_EVENTS_DDL),
    ("interventions", INTERVENTIONS_DDL),
    ("artifacts", ARTIFACTS_DDL),
    ("repo_symbols", REPO_GRAPH_DDL),
    ("repo_edges", REPO_GRAPH_DDL),
    ("routing_stats", ROUTING_STATS_DDL),
    ("token_ledger", TOKEN_LEDGER_DDL),
)

_QUARANTINE_TABLES = ("forge_sessions", "app_settings")


def _ensure_quarantine(conn: sqlite3.Connection) -> None:
    """隔离表自身必须先存在，否则损坏数据无处可放。"""
    conn.executescript(QUARANTINE_DDL)
    conn.commit()


def _isolate_broken_rows(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """把**读取失败**的行移入隔离表。返回 (隔离条数, 描述列表)。

    SQLite 的 `integrity_check` 只报告结构问题；行级损坏（非法编码等）只能靠
    实际读取发现——而 `fetchall()` 遇坏行会整体抛错，所以必须**逐行**试探：
    先取 rowid 列表（只读主键，通常不受影响），再逐个读取内容。

    损坏行的内容本就读不出来，故 `row_json` 只记 `{"rowid": N}` 与原因，
    **不猜测原始内容**（MUST-19：不得把无法读取的数据写进任何日志或响应）。
    """
    quarantined = 0
    issues: list[str] = []
    for table in _QUARANTINE_TABLES:
        try:
            rowids = [r[0] for r in conn.execute(f"SELECT rowid FROM {table}")]  # noqa: S608 - 常量表名
        except sqlite3.DatabaseError as exc:
            issues.append(f"{table}: 表级损坏，无法逐行定位（{type(exc).__name__}）")
            continue
        for rowid in rowids:
            try:
                conn.execute(f"SELECT * FROM {table} WHERE rowid=?", (rowid,)).fetchone()  # noqa: S608
            except sqlite3.DatabaseError:
                pass  # 行完好
            else:
                continue
            # 走到这里说明读取抛错 → 该行损坏
            try:
                conn.execute(
                    "INSERT INTO forge_quarantine (table_name, row_json, reason) VALUES (?,?,?)",
                    (table, f'{{"rowid": {rowid}}}', "row_unreadable"),
                )
                conn.execute(f"DELETE FROM {table} WHERE rowid=?", (rowid,))  # noqa: S608
                quarantined += 1
            except sqlite3.DatabaseError as exc:
                issues.append(f"{table}: 损坏行无法隔离（{type(exc).__name__}）")
    conn.commit()
    return quarantined, issues


#: 孤儿判定阈值（分钟）：远大于单轮最长耗时，避免误杀正在跑的 turn。
ORPHAN_TURN_MINUTES = 30


def _abort_orphan_turns(
    conn: sqlite3.Connection, older_than_minutes: int = ORPHAN_TURN_MINUTES
) -> int:
    """把崩溃遗留的未完成 turn 与会话收尾，返回受影响会话数。

    只处理「超过阈值仍停在 INIT / AGENTIC」的行：进程在 agentic 循环里被强杀时
    turn 停在 AGENTIC、会话也停在 AGENTIC，此后 start_turn 会一直拒绝（6001）。
    多实例部署需改为按实例心跳判定（当前单机单用户不适用）。
    """
    cutoff = f"-{max(1, older_than_minutes)} minutes"
    try:
        conn.execute(ORPHAN_TURNS_SQL, (cutoff,))
        cursor = conn.execute(ORPHAN_SESSIONS_SQL, (cutoff,))
    except sqlite3.Error:
        # 自愈失败不阻断启动：留给下一次启动重试
        return 0
    return cursor.rowcount if cursor.rowcount > 0 else 0


def run_startup_safety_check(db_path: str) -> StartupRepairReport:
    """执行一次启动自愈并记录报告。**永不抛异常**——体检失败不应阻止服务启动。

    流程：确保隔离表存在 → `integrity_check` → 逐行隔离坏行 → 补齐缺失表。
    报告经 `domain.startup_report.record_report` 落地，供 `/health` 读取。
    """
    path = Path(db_path).expanduser()
    issues: list[str] = []
    repaired: list[str] = []
    quarantined = 0

    if not path.parent.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            repaired.append("数据目录")
        except OSError as exc:
            report = StartupRepairReport(
                action=ACTION_FAILED, issues=(f"数据目录不可创建：{type(exc).__name__}",)
            )
            record_report(report)
            return report

    # connect 前判断：`sqlite3.connect` 会创建文件，之后就分不出「全新初始化」与「既有库缺表」
    is_fresh_db = not path.exists()
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
    except sqlite3.Error as exc:
        report = StartupRepairReport(
            action=ACTION_FAILED, issues=(f"数据库不可打开：{type(exc).__name__}",)
        )
        record_report(report)
        return report

    try:
        _ensure_quarantine(conn)

        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_text = str(integrity[0]) if integrity else "unknown"
        if integrity_text != "ok":
            issues.append(f"完整性检查未通过：{integrity_text}")
            quarantined, row_issues = _isolate_broken_rows(conn)
            issues.extend(row_issues)

        for table, ddl in _REQUIRED_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if exists:
                continue
            try:
                conn.executescript(ddl)
                # 全新库的建表属正常初始化，不算「修复」——否则每次首启都报异常
                if not is_fresh_db:
                    repaired.append(table)
            except sqlite3.DatabaseError as exc:
                issues.append(f"{table}: 补建失败（{type(exc).__name__}）")
        orphan_sessions = _abort_orphan_turns(conn)
        if orphan_sessions:
            # 计数入 repaired（只报数量，不含行内容，MUST-19）
            repaired.append(f"orphan_session:{orphan_sessions}")
        conn.commit()
    except sqlite3.Error as exc:
        issues.append(f"自愈过程异常：{type(exc).__name__}")
    finally:
        conn.close()

    if quarantined:
        action = ACTION_QUARANTINED
    elif repaired or issues:
        action = ACTION_REPAIRED
    else:
        action = ACTION_OK
    report = StartupRepairReport(
        action=action,
        repaired=tuple(repaired),
        quarantined=quarantined,
        issues=tuple(issues),
    )
    record_report(report)
    if action != ACTION_OK:
        # 修复事件走 observability（N-1）；载荷只含计数，绝不含行内容（MUST-19）
        emit(
            "startup.repair",
            action=action,
            repaired=len(repaired),
            quarantined=quarantined,
            issues=len(issues),
        )
    return report
