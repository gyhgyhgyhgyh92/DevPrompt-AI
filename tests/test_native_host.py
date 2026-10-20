"""native messaging host 的协议与安全边界测试（2026-10-19）。"""

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import threading

import pytest

from devprompt_ai import native_host
from devprompt_ai.harness.dialog import _PS_SCRIPT, _UTF8_STDOUT
from devprompt_ai.native_host import (
    PICK_FOLDER,
    _caller_allowed,
    _handle,
    decode_message,
    encode_message,
    read_message,
)


class TestProtocol:
    def test_roundtrip(self) -> None:
        raw = encode_message({"type": PICK_FOLDER})
        # 4 字节小端长度前缀 + UTF-8 JSON
        (size,) = struct.unpack("=I", raw[:4])
        assert size == len(raw) - 4
        assert json.loads(raw[4:].decode("utf-8")) == {"type": PICK_FOLDER}
        assert decode_message(raw) == {"type": PICK_FOLDER}

    def test_non_ascii_path_survives(self) -> None:
        path = "D:/我的 项目/repo"
        assert decode_message(encode_message({"path": path}))["path"] == path

    @pytest.mark.parametrize(
        "raw",
        [
            b"",
            b"\x01\x02",
            struct.pack("=I", 0) + b"{}",
            struct.pack("=I", 10) + b"{}",
            encode_message({})[:-1],
        ],
    )
    def test_malformed_raises(self, raw: bytes) -> None:
        with pytest.raises(ValueError):
            decode_message(raw)

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(ValueError):
            decode_message(_raw_json("[1,2]"))


def _raw_json(text: str) -> bytes:
    body = text.encode("utf-8")
    return struct.pack("=I", len(body)) + body


class TestStreamRead:
    """Chrome 发完消息**不关 stdin**：读到 EOF 的实现会永久阻塞（2026-10-19 真实故障：
    前端一直停在「正在打开...」）。"""

    def test_returns_before_stdin_closes(self) -> None:
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb")
        try:
            os.write(write_fd, encode_message({"type": PICK_FOLDER}))
            # 故意保持 write_fd 打开，模拟浏览器握着管道不放
            box: dict[str, object] = {}
            reader = threading.Thread(target=lambda: box.update(msg=read_message(stream)))
            reader.start()
            reader.join(5)
            assert not reader.is_alive(), "读到 EOF 的实现在浏览器下会永久阻塞"
            assert box["msg"] == {"type": PICK_FOLDER}
        finally:
            stream.close()
            os.close(write_fd)

    def test_truncated_stream_raises(self) -> None:
        with pytest.raises(ValueError):
            read_message(io.BytesIO(struct.pack("=I", 10) + b"{}"))


class TestCallerCheck:
    def test_extension_origin_allowed(self) -> None:
        assert _caller_allowed(["chrome-extension://abcdefghijklmnop/"]) is True

    def test_other_process_refused(self) -> None:
        assert _caller_allowed([]) is False
        assert _caller_allowed(["--some-flag"]) is False
        assert _caller_allowed(["C:\\\\evil.exe"]) is False

    def test_manual_debug_flag_allowed(self) -> None:
        assert _caller_allowed(["--allow-any-caller"]) is True


class TestDialogStdoutEncoding:
    """pwsh 的 stdout 编码跟随 console：Chrome（GUI 进程）拉起宿主时**没有 console**，
    代码页退化为 936，中文路径经 run_command 的 UTF-8 解码变成 U+FFFD
    （2026-10-19 真实故障：``D:\\前端作业`` 显示成乱码）。"""

    _CJK_PATH = "D:\\前端作业\\实验二"

    def test_script_pins_utf8_stdout(self) -> None:
        assert _PS_SCRIPT.startswith(_UTF8_STDOUT)

    @pytest.mark.skipif(
        sys.platform != "win32" or shutil.which("pwsh") is None,
        reason="需要 Windows + pwsh",
    )
    def test_chinese_path_survives_without_console(self) -> None:
        # CREATE_NO_WINDOW = 无 console，与 Chrome 拉起宿主的环境一致
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-STA",
                "-Command",
                _UTF8_STDOUT + f"[Console]::Out.Write('{self._CJK_PATH}')",
            ],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=60,
        )
        assert result.stdout.decode("utf-8") == self._CJK_PATH


class TestHandle:
    def test_unknown_type_refused(self) -> None:
        reply = _handle({"type": "rm_rf"})
        assert reply["ok"] is False
        assert "unsupported" in reply["error"]

    def test_pick_folder_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake() -> str:
            return "D:/ws/repo"

        monkeypatch.setattr(native_host, "pick_folder_dialog", fake)
        assert _handle({"type": PICK_FOLDER}) == {"ok": True, "path": "D:/ws/repo"}

    def test_pick_folder_cancel_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake() -> str:
            return ""

        monkeypatch.setattr(native_host, "pick_folder_dialog", fake)
        assert _handle({"type": PICK_FOLDER}) == {"ok": True, "path": ""}

    def test_dialog_error_has_no_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from devprompt_ai.domain.errors import DevPromptError

        async def fake() -> str:
            raise DevPromptError("系统文件夹选择器当前仅支持 Windows", code=9001)

        monkeypatch.setattr(native_host, "pick_folder_dialog", fake)
        reply = _handle({"type": PICK_FOLDER})
        assert reply["ok"] is False
        assert "Windows" in reply["error"]
