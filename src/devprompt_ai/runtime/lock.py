"""单写者锁（F5）：同一 SQLite 只允许一个进程写入。

为什么需要：两个进程同时写会话库，会把运行中的会话写成「假中断」，并吞掉事件；
天枢在 sidecar 里为同一目的加了独占锁（`serve.ts:730-734`）。

实现是**带心跳的文件锁**：
- `<db>.lock` 由 `O_CREAT|O_EXCL` 原子创建，内容只记 pid 与实例 id（便于排查）；
- 后台线程每 30s 刷新 mtime 作为心跳；
- 进程崩溃后锁文件留在原地，超过 `stale_after_s`（默认 120s）即视为过期，可被接管；
- 同进程重复获取直接复用（单例），避免测试/多次装配互相打架。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from devprompt_ai.domain.errors import DevPromptError

_LOCK_SUFFIX = ".lock"
_HEARTBEAT_S = 30.0


class WriterLockError(DevPromptError):
    """另一个进程正持有同一个数据库的写锁（启动期硬失败）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=9001, context={"reason": "writer_lock_held"})


class SingleWriterLock:
    """带心跳的独占文件锁；`acquired=False` 表示未启用（no-op）。"""

    def __init__(
        self,
        db_path: str,
        *,
        stale_after_s: float = 120.0,
        heartbeat_s: float = _HEARTBEAT_S,
    ) -> None:
        self._lock_path = Path(f"{Path(db_path).expanduser()}{_LOCK_SUFFIX}")
        self._stale_after_s = stale_after_s
        self._heartbeat_s = heartbeat_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.acquired = False

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                self._create()
            except FileExistsError:
                if attempt == 1 and self._is_stale():
                    self._lock_path.unlink(missing_ok=True)
                    continue
                raise WriterLockError("另一个进程正在使用同一个数据库，请关闭它后重试") from None
            self.acquired = True
            self._start_heartbeat()
            return
        raise WriterLockError("无法获取数据库写锁")

    def release(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None
        if self.acquired:
            self._lock_path.unlink(missing_ok=True)
            self.acquired = False

    def _create(self) -> None:
        fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            payload = json.dumps({"pid": os.getpid(), "instance": uuid.uuid4().hex})
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self._lock_path.stat().st_mtime
        except FileNotFoundError:
            return True
        return age > self._stale_after_s

    def _start_heartbeat(self) -> None:
        def _beat() -> None:
            while not self._stop.wait(self._heartbeat_s):
                try:
                    os.utime(self._lock_path)
                except FileNotFoundError:
                    return

        self._thread = threading.Thread(target=_beat, name="writer-lock-heartbeat", daemon=True)
        self._thread.start()


#: 同进程复用表：key 为归一化后的锁路径。
_HELD: dict[str, SingleWriterLock] = {}


def acquire_writer_lock(
    db_path: str,
    *,
    enabled: bool = True,
    stale_after_s: float = 120.0,
    heartbeat_s: float = _HEARTBEAT_S,
) -> SingleWriterLock:
    """获取写锁；同进程重复调用返回同一实例（引用计数由 release 统一处理）。"""
    if not enabled:
        return SingleWriterLock(db_path)
    key = str(Path(f"{Path(db_path).expanduser()}{_LOCK_SUFFIX}").absolute())
    existing = _HELD.get(key)
    if existing is not None and existing.acquired:
        return existing
    lock = SingleWriterLock(db_path, stale_after_s=stale_after_s, heartbeat_s=heartbeat_s)
    lock.acquire()
    _HELD[key] = lock
    return lock


def release_writer_lock(lock: SingleWriterLock) -> None:
    key = str(lock.lock_path.absolute())
    if _HELD.get(key) is lock:
        _HELD.pop(key, None)
        lock.release()
