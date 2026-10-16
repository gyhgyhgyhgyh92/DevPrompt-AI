"""启动自愈测试（N-1）。

覆盖三类场景：正常库零写入、缺表补建、损坏行隔离。
隔离验证用「真实写入非法字节」构造损坏——这是本地 SQLite 唯一可靠的造损坏方式
（`PRAGMA writable_schema` 改表定义会直接破坏文件头）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from devprompt_ai.domain.startup_report import (
    ACTION_OK,
    ACTION_REPAIRED,
    StartupRepairReport,
    latest_report,
    reset_report,
)
from devprompt_ai.memory.startup_safety_check import _isolate_broken_rows, run_startup_safety_check


@pytest.fixture(autouse=True)
def _clear_report() -> Iterator[None]:
    """进程级状态必须隔离，否则用例间串味。"""
    reset_report()
    yield
    reset_report()


def _rows(db: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestHealthyDatabase:
    def test_fresh_path_is_ok(self, tmp_path: Path) -> None:
        report = run_startup_safety_check(str(tmp_path / "new.db"))
        assert report.action == ACTION_OK
        assert report.is_ok
        assert report.quarantined == 0
        assert report.repaired == ()

    def test_records_report_for_health_to_read(self, tmp_path: Path) -> None:
        run_startup_safety_check(str(tmp_path / "a.db"))
        assert latest_report().action == ACTION_OK

    def test_no_write_on_healthy_db(self, tmp_path: Path) -> None:
        """健康库启动必须零写入——否则每次启动都无谓改文件。"""
        db = tmp_path / "ok.db"
        run_startup_safety_check(str(db))
        before = db.stat().st_mtime_ns
        run_startup_safety_check(str(db))
        assert db.stat().st_mtime_ns == before


class TestMissingTables:
    def test_creates_missing_tables(self, tmp_path: Path) -> None:
        db = tmp_path / "partial.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE forge_sessions (session_id TEXT)")
        conn.commit()
        conn.close()

        report = run_startup_safety_check(str(db))
        assert report.action == ACTION_REPAIRED
        assert "preference_vectors" in report.repaired
        # forge_quarantine 由 _ensure_quarantine 在补建循环之前建好，不算「修复既有库」
        assert "forge_quarantine" not in report.repaired

    def test_repaired_tables_are_readable_afterwards(self, tmp_path: Path) -> None:
        db = tmp_path / "partial2.db"
        sqlite3.connect(str(db)).close()
        run_startup_safety_check(str(db))
        names = {r[0] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"forge_sessions", "preference_vectors", "app_settings", "forge_quarantine"} <= names

    def test_quarantine_table_always_created(self, tmp_path: Path) -> None:
        db = tmp_path / "q.db"
        run_startup_safety_check(str(db))
        names = {r[0] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "forge_quarantine" in names


class TestFileLevelCorruption:
    """文件级损坏：真实可构造（改文件头），是本地 SQLite 最常见的损坏形态。

    注：**行级损坏在 SQLite 中几乎不可构造** —— 往TEXT 列写非法 UTF-8 字节后，
    Python sqlite3 会把它当合法 BLOB 返回，`PRAGMA integrity_check` 仍为 `ok`，
    `SELECT *` 也不抛错（实测）。故行级隔离逻辑改用注入方式验证，见 TestRowIsolation。
    """

    def test_corrupted_header_is_reported(self, tmp_path: Path) -> None:
        db = tmp_path / "hdr.db"
        run_startup_safety_check(str(db))
        raw = bytearray(db.read_bytes())
        raw[0:16] = b"\x00" * 16  # 破坏 SQLite 文件头魔数
        db.write_bytes(bytes(raw))

        report = run_startup_safety_check(str(db))
        assert report.action != ACTION_OK
        assert report.issues, "损坏须在 issues 中说明"

    def test_truncated_file_does_not_crash(self, tmp_path: Path) -> None:
        db = tmp_path / "trunc.db"
        run_startup_safety_check(str(db))
        raw = db.read_bytes()
        db.write_bytes(raw[: len(raw) // 2])

        report = run_startup_safety_check(str(db))
        assert isinstance(report, StartupRepairReport)

    def test_report_never_contains_raw_bytes(self, tmp_path: Path) -> None:
        """MUST-19：报告只含计数与分类，不得带出原始数据。"""
        db = tmp_path / "leak.db"
        run_startup_safety_check(str(db))
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('sk-secret-value', 'x')")
        conn.commit()
        conn.close()

        report = run_startup_safety_check(str(db))
        blob = " ".join(report.issues) + " ".join(report.repaired)
        assert "sk-secret-value" not in blob


class _FlakyConnection:
    """连接包装：只让指定表的 `SELECT *` 读取失败。

    `sqlite3.Connection` 是不可变类型，无法 monkeypatch 其方法，故用代理包装。
    """

    def __init__(self, real: sqlite3.Connection, fail_table: str = "forge_sessions") -> None:
        self._real = real
        self._fail_table = fail_table

    def execute(self, sql: str, params: object = ()) -> sqlite3.Cursor:
        if sql.startswith(f"SELECT * FROM {self._fail_table}"):
            raise sqlite3.DatabaseError("injected read failure")
        return self._real.execute(sql, params)  # type: ignore[arg-type]

    def commit(self) -> None:
        self._real.commit()


class TestRowIsolation:
    """行级隔离：防御性逻辑。真实损坏难以构造（见 TestFileLevelCorruption 说明），
    故直接对内部函数 `_isolate_broken_rows` 注入读取失败来验证。"""

    @pytest.fixture
    def seeded_db(self, tmp_path: Path) -> Path:
        db = tmp_path / "rows.db"
        run_startup_safety_check(str(db))
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO forge_sessions (session_id, user_id, state, version, payload)"
            " VALUES ('s-secret','local','DONE',0,'{}')"
        )
        conn.commit()
        conn.close()
        return db

    def test_isolates_rows_whose_read_fails(self, seeded_db: Path) -> None:
        conn = sqlite3.connect(str(seeded_db))
        count, issues = _isolate_broken_rows(_FlakyConnection(conn))  # type: ignore[arg-type]
        conn.close()
        assert count >= 1, "读取失败的行应被隔离"
        assert not issues, f"注入的失败属预期路径，不应记为异常：{issues}"

    def test_isolated_row_is_removed_from_source_table(self, seeded_db: Path) -> None:
        """关键设计：隔离而非删除——本地单用户工具误删不可恢复。"""
        conn = sqlite3.connect(str(seeded_db))
        _isolate_broken_rows(_FlakyConnection(conn))  # type: ignore[arg-type]
        conn.commit()
        remaining = conn.execute("SELECT session_id FROM forge_sessions").fetchall()
        quarantined = conn.execute("SELECT table_name, reason FROM forge_quarantine").fetchall()
        conn.close()
        assert remaining == [], "损坏行应从源表移除"
        assert any(t == "forge_sessions" for t, _ in quarantined), "但须留在隔离表里"

    def test_quarantine_stores_no_guessed_content(self, seeded_db: Path) -> None:
        """损坏行内容读不出来，隔离表只记 rowid，不得猜测内容（MUST-19）。"""
        conn = sqlite3.connect(str(seeded_db))
        _isolate_broken_rows(_FlakyConnection(conn))  # type: ignore[arg-type]
        stored = conn.execute("SELECT row_json FROM forge_quarantine").fetchall()
        conn.close()
        assert stored, "应有隔离记录"
        assert "s-secret" not in str(stored[0][0]), "不得把读不出的内容猜出来写进隔离表"
        assert "rowid" in str(stored[0][0]), "只记 rowid 便于人工回查"

    def test_healthy_rows_are_untouched(self, seeded_db: Path) -> None:
        """无注入时不得隔离任何行——避免把正常数据误判为损坏。"""
        conn = sqlite3.connect(str(seeded_db))
        count, issues = _isolate_broken_rows(conn)
        conn.close()
        assert count == 0
        assert not issues
        assert _rows(seeded_db, "SELECT session_id FROM forge_sessions") == [("s-secret",)]


class TestNeverRaises:
    def test_unopenable_path_returns_failed_report(self, tmp_path: Path) -> None:
        """体检失败不得阻止服务启动——须返回 failed 报告而非抛异常。"""
        blocker = tmp_path / "notadir"
        blocker.write_text("x", encoding="utf-8")
        report = run_startup_safety_check(str(blocker / "sub" / "x.db"))
        assert report.action != ACTION_OK
        assert report.issues

    def test_garbage_file_does_not_crash(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.db"
        junk.write_bytes(b"this is definitely not a sqlite file at all")
        report = run_startup_safety_check(str(junk))
        assert isinstance(report, StartupRepairReport)


class TestReportShape:
    def test_summary_reports_counts_not_names(self) -> None:
        """摘要只给数量与分类——表名属于内部结构，无须暴露给health 消费方。"""
        report = StartupRepairReport(
            action=ACTION_REPAIRED, repaired=("forge_sessions", "app_settings")
        )
        assert "2" in report.summary()
        assert "forge_sessions" not in report.summary()

    def test_ok_summary_is_short(self) -> None:
        assert StartupRepairReport().summary() == "存储结构完整，无需修复"
