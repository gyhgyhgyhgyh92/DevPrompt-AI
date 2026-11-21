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
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

from devprompt_ai.domain.errors import DevPromptError

_LOCK_SUFFIX = ".lock"
_HEARTBEAT_S = 30.0
#: 本进程启动时刻（epoch ms）：用于防 PID 复用（天枢 StoreLock 的 pid_reused 语义）。
_PROCESS_STARTED_AT_MS = int((time.time() - time.monotonic()) * 1000)
#: PID 启动时间比对容差：秒级抖动属正常，超过即判为「号码被复用」。
_PID_START_TOLERANCE_MS = 5000


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
            payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "instance": uuid.uuid4().hex,
                    "startedAtMs": _PROCESS_STARTED_AT_MS,
                    "machineId": socket.gethostname(),
                }
            )
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)

    def _is_stale(self) -> bool:
        """可接管判据：身份读不出/进程已死/PID 被复用/心跳超时（对齐天枢 StoreLock）。"""
        try:
            payload = json.loads(self._lock_path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
        except (OSError, ValueError, TypeError):
            return True  # 畸形锁无法证明有人持有
        try:
            age = time.time() - self._lock_path.stat().st_mtime
        except FileNotFoundError:
            return True

        if pid <= 0:
            return True
        if not _pid_alive(pid):
            return True  # pid_dead：死进程立即接管，不等 stale

        if str(payload.get("machineId") or "") != socket.gethostname():
            return age > self._stale_after_s  # 跨主机判不了死活：只按心跳超时

        started = payload.get("startedAtMs")
        if not isinstance(started, int):
            return age > self._stale_after_s  # 旧格式锁不可核验：保守等心跳超时
        actual = _pid_started_at_ms(pid)
        if actual is None:
            return age > self._stale_after_s  # 探测不了也保守
        if abs(actual - started) > _PID_START_TOLERANCE_MS:
            return True  # pid_reused：号码被复用，原持有者已不存在
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


def _pid_started_at_ms(pid: int) -> int | None:
    """进程真实启动时刻（epoch ms）；探测不了返回 None，调用方据此保守处理。"""
    # sys.platform 而非 os.name：mypy 按 platform 剪枝，Linux runner 上不检查
    # Windows-only 的 ctypes.windll 分支（os.name 不触发剪枝）。
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        try:
            created = _FileTime()
            exited = _FileTime()
            kernel = _FileTime()
            user = _FileTime()
            ok = ctypes.windll.kernel32.GetProcessTimes(
                process,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            if not ok:
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return int(ticks / 10_000 - 11644473600000)  # FILETIME(100ns since 1601) → epoch ms
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # 第 22 字段（去掉 pid/comm 后索引 19）
        with open("/proc/stat", encoding="utf-8") as handle:
            btime = next(int(line.split()[1]) for line in handle if line.startswith("btime"))
        # os.sysconf 只在 POSIX 存在：Windows 上类型检查报 attr-defined，
        # POSIX 上该 ignore 又会变成 unused-ignore，故两个码一起列。
        clock_ticks = int(os.sysconf("SC_CLK_TCK"))  # type: ignore[attr-defined, unused-ignore]
        return int((btime + start_ticks / clock_ticks) * 1000)
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _pid_alive(pid: int) -> bool:
    """进程存活检测：Windows 用 OpenProcess，POSIX 用 kill(pid, 0)。"""
    if sys.platform == "win32":
        import ctypes

        # PROCESS_QUERY_LIMITED_INFORMATION
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限：按存活处理，避免误接管
    return True


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
