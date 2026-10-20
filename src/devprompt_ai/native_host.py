"""Chrome/Edge native messaging host：弹系统原生文件夹选择器，把绝对路径回传扩展。

## 为什么需要它

浏览器的文件选择 API **刻意不暴露绝对路径**——File System Access API 的
`showDirectoryPicker()` 只给 `dirHandle`（"For security reasons the full path will
not be revealed"），`<input webkitdirectory>` 只给 `webkitRelativePath`。而本项目的
`GET /project/scan` 需要绝对路径去 `os.scandir`，故唯一可行链路是
**扩展 → native messaging → 原生进程**。

## 协议

Chrome/Edge 的 native messaging：stdin / stdout 传 **4 字节小端长度 + UTF-8 JSON**。
每次消息浏览器**重新拉起**进程，故本模块读一条、写一条即退出（不常驻）。

请求只接受一种（攻击面最小化）::

    {"type": "pick_folder"}

回复::

    {"ok": true, "path": "D:\\\\Works\\\\..."}   # 用户取消时 path 为空串
    {"ok": false, "error": "仅支持 Windows"}     # 错误文案不回传路径本体（MUST-19）

## 安全边界

- **校验调用方**：Chrome 拉起 host 时把扩展 origin 作为 ``argv[1]`` 传入；非
  ``chrome-extension://`` 开头的调用一律拒绝——否则任何本地进程都能直接跑这个
  exe 骗出对话框。手动调试用 ``--allow-any-caller`` 显式放行。
- **只认一种消息**：其余 type 回 ``unsupported``，不做任何转发或副作用。
- **错误不回传路径**：路径只出现在成功回复里（用户自己刚选的位置）。

宿主 exe 由 ``[project.scripts] devprompt-ai-pick-folder`` 暴露
（2026-10-19 新增）。安装方式见 ``scripts/install_native_picker.ps1``。
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from typing import Any, BinaryIO, Final

from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.harness.dialog import pick_folder_dialog

#: 唯一支持的消息类型；其余一律拒绝（最小攻击面）。
PICK_FOLDER: Final = "pick_folder"

#: 读入消息的防御上限。非文档上限：官方约定「宿主发往浏览器」上限 1 MB、
#: 「浏览器发往宿主」上限 4 GB；一条请求只有 type 字段，这里取个宽裕的防呆值。
_MAX_MESSAGE_BYTES: Final = 4 * 1024 * 1024

#: 合法调用方前缀（Chromium 系扩展）。
_EXTENSION_ORIGIN_PREFIXES: Final = ("chrome-extension://", "moz-extension://")

#: 手动调试放行开关（本机直接跑 exe 时用；浏览器拉起时绝不出现）。
_ALLOW_ANY_CALLER: Final = "--allow-any-caller"


def encode_message(payload: dict[str, Any]) -> bytes:
    """编码一条「4 字节小端长度 + UTF-8 JSON」消息。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return struct.pack("=I", len(body)) + body


def decode_message(raw: bytes) -> dict[str, Any]:
    """解码一条消息。

    :raises ValueError: 头/体不完整、长度非法、JSON 不合法或不是对象。
    """
    if len(raw) < 4:
        raise ValueError("消息头不完整")
    (size,) = struct.unpack("=I", raw[:4])
    if size == 0 or size > _MAX_MESSAGE_BYTES:
        raise ValueError("消息长度非法")
    body = raw[4 : 4 + size]
    if len(body) != size:
        raise ValueError("消息体不完整")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("消息必须是 JSON 对象")
    return data


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    """读满 size 字节。

    不能用 ``stream.read()`` 读到 EOF：Chrome 发完消息**不关 stdin**（宿主存活期间管道
    一直开着），读到 EOF 的实现会永久阻塞、一个字节都不回，前端于是永远停在「正在打开」。
    """
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError("stdin 提前结束")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> dict[str, Any]:
    """从流里读一条消息：按长度精确读，不依赖 EOF。

    :raises ValueError: 长度非法或流提前结束。
    """
    header = _read_exact(stream, 4)
    (size,) = struct.unpack("=I", header)
    if size == 0 or size > _MAX_MESSAGE_BYTES:
        raise ValueError("消息长度非法")
    return decode_message(header + _read_exact(stream, size))


def _handle(message: dict[str, Any]) -> dict[str, Any]:
    """处理一条请求（同步包装，便于单测直接调用）。"""
    if message.get("type") != PICK_FOLDER:
        return {"ok": False, "error": f"unsupported message type: {message.get('type')!r}"}
    try:
        path = asyncio.run(pick_folder_dialog())
    except DevPromptError as exc:
        # DevPromptError 没有 .message 属性，message 已在 __init__ 里作为 args 传入
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 宿主须把任何失败转成回复而非裸崩
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": True, "path": path}


def _caller_allowed(args: list[str]) -> bool:
    """Chrome 拉起时 ``argv[1]`` 是扩展 origin；手动调试需显式开关。"""
    if _ALLOW_ANY_CALLER in args:
        return True
    return any(arg.startswith(_EXTENSION_ORIGIN_PREFIXES) for arg in args)


def main() -> int:
    """宿主入口：校验调用方 → 读一条 → 回一条 → 退出。"""
    args = sys.argv[1:]
    if not _caller_allowed(args):
        print(
            "refuse: caller must be a browser extension (argv[1] starts with "
            f"{', '.join(_EXTENSION_ORIGIN_PREFIXES)}) or pass {_ALLOW_ANY_CALLER}",
            file=sys.stderr,
        )
        return 2
    try:
        message = read_message(sys.stdin.buffer)
    except ValueError as exc:
        sys.stdout.buffer.write(encode_message({"ok": False, "error": f"bad message: {exc}"}))
        sys.stdout.buffer.flush()
        return 0
    sys.stdout.buffer.write(encode_message(_handle(message)))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
