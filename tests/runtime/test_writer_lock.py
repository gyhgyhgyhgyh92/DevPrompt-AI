"""单写者锁测试：互斥、同进程复用、崩溃后过期接管、禁用时 no-op。"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from devprompt_ai.runtime.lock import (
    SingleWriterLock,
    WriterLockError,
    acquire_writer_lock,
    release_writer_lock,
)


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "app.db")


def test_acquire_creates_lock_and_release_removes_it(tmp_path: Path) -> None:
    lock = SingleWriterLock(_db(tmp_path))
    lock.acquire()

    assert lock.acquired is True
    assert lock.lock_path.exists()

    lock.release()
    assert lock.acquired is False
    assert not lock.lock_path.exists()


def test_fresh_foreign_lock_blocks_second_process(tmp_path: Path) -> None:
    path = Path(f"{_db(tmp_path)}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pid": 999999}', encoding="utf-8")

    lock = SingleWriterLock(_db(tmp_path))
    with pytest.raises(WriterLockError):
        lock.acquire()


def test_stale_lock_is_taken_over(tmp_path: Path) -> None:
    path = Path(f"{_db(tmp_path)}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pid": 999999}', encoding="utf-8")
    old = time.time() - 600
    os.utime(path, (old, old))

    lock = SingleWriterLock(_db(tmp_path), stale_after_s=120)
    lock.acquire()

    assert lock.acquired is True
    lock.release()


def test_same_process_reuses_lock(tmp_path: Path) -> None:
    first = acquire_writer_lock(_db(tmp_path))
    second = acquire_writer_lock(_db(tmp_path))

    assert first is second
    release_writer_lock(first)
    assert not first.lock_path.exists()


def test_disabled_lock_is_noop(tmp_path: Path) -> None:
    lock = acquire_writer_lock(_db(tmp_path), enabled=False)

    assert lock.acquired is False
    assert not lock.lock_path.exists()
    release_writer_lock(lock)


async def test_runtime_bootstrap_acquires_and_releases_lock(tmp_path: Path) -> None:
    """装配时拿锁、reset 时释放——这是防多进程写坏会话的入口。"""
    from typing import cast

    from devprompt_ai.runtime.bootstrap import get_runtime, reset_runtime
    from devprompt_ai.service import ForgeService

    class _Cfg:
        db_path = str(tmp_path / "app.db")
        single_writer_lock = True
        writer_lock_stale_seconds = 120.0

    class _Svc:
        config = _Cfg()

    reset_runtime()
    await get_runtime(cast(ForgeService, _Svc()), lambda _snapshot: {})
    lock_path = f"{_Cfg.db_path}.lock"

    assert await asyncio.to_thread(os.path.exists, lock_path)

    reset_runtime()
    assert not await asyncio.to_thread(os.path.exists, lock_path)
