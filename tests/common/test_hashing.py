"""common/hashing.py 测试。"""

import os
import time
from pathlib import Path

from devprompt_ai.common.hashing import mtime_digest, sha256_hex


def test_sha256_hex_deterministic() -> None:
    assert sha256_hex("abc") == sha256_hex("abc")
    assert sha256_hex("abc") != sha256_hex("abd")
    assert len(sha256_hex("abc")) == 64


def test_mtime_digest_order_insensitive(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("1", encoding="utf-8")
    b.write_text("2", encoding="utf-8")
    d1 = mtime_digest([(str(a), a.stat().st_mtime_ns), (str(b), b.stat().st_mtime_ns)])
    d2 = mtime_digest([(str(b), b.stat().st_mtime_ns), (str(a), a.stat().st_mtime_ns)])
    assert d1 == d2  # 排序后摘要，与传入顺序无关


def test_mtime_digest_changes_on_mtime(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("1", encoding="utf-8")
    before = mtime_digest([(str(f), f.stat().st_mtime_ns)])
    os.utime(f, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    after = mtime_digest([(str(f), f.stat().st_mtime_ns)])
    assert before != after
