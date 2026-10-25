"""桌面端 sidecar 入口：Electron 桌面壳拉起的 Python 子进程（仅 Windows 分发形态）。

与 Web 形态入口 main.py 的分工：

- ``main.py``：``uv run devprompt-ai``，固定 8000，输出面向人类终端；
- 本模块：被 Electron 主进程 spawn，输出面向**程序解析**——
  1. 127.0.0.1 绑定随机端口，把已绑定 socket 直接交给 uvicorn
     （消除「先取端口再回传」被抢占的竞态；随机端口也天然避开 Web 版 8000）；
  2. 就绪后向 stdout 打印单行 ``DPROMPT_READY {"port": N}`` 并 flush。
     uvicorn 默认把 access 日志写在 stdout，会污染协议流，故显式改道 stderr；
  3. 优雅退出复用 uvicorn 自带信号处理（Windows 含 SIGBREAK），SQLite WAL 不留锁。

业务逻辑零改动：serve 的就是 ``interfaces.api.app:app`` 同一实例（MUST-10）。
本模块不 import 任何基础设施实现模块（薄壳约束，同 main.py）。
"""

from __future__ import annotations

import copy
import json
import socket
import sys
from typing import Any

#: 仅监听回环：桌面壳与 sidecar 同机，无对外暴露面（与 main.py 的本地工具定位一致）
HOST = "127.0.0.1"
#: stdout 就绪协议前缀；主进程（desktop/src/main.ts）按此前缀 + 单行 JSON 解析
READY_LINE_PREFIX = "DPROMPT_READY"


def bind_ephemeral_socket(host: str = HOST) -> socket.socket:
    """在 host 上绑定随机端口并 listen，返回已绑定 socket。

    端口由内核分配（port 0），已 listen 的 socket 直接交给 uvicorn——
    不存在「sidecar 先报端口、uvicorn 后 bind」之间被其他进程抢占的窗口。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(128)
    return sock


def _emit_ready(port: int) -> None:
    """向 stdout 打印单行就绪协议并 flush；此后 stdout 不再写任何内容。"""
    line = f"{READY_LINE_PREFIX} {json.dumps({'port': port}, separators=(',', ':'))}"
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _stderr_access_log_config() -> dict[str, Any]:
    """uvicorn 默认日志配置的副本：access 日志从 stdout 改道 stderr。

    uvicorn 默认 default handler（自身启动日志）已在 stderr，但 access handler
    在 stdout——每请求一行会混进协议流，主进程按行解析必崩。deepcopy 后只改
    这一个键，不动 uvicorn 模块级配置（其他进程还要用）。
    """
    import uvicorn.config

    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    config["handlers"]["access"]["stream"] = "ext://sys.stderr"
    return config


def main() -> int:
    """sidecar 入口：绑定随机端口 → 起 uvicorn（socket 直传）→ 阻塞至退出信号。

    返回进程退出码。uvicorn 的 ``Server.run`` 内部以 ``capture_signals`` 接管
    SIGINT/SIGTERM/SIGBREAK（Windows 三者全有），优雅关停无需自注册信号处理器。
    """
    import uvicorn

    from devprompt_ai.interfaces.api.app import app as fastapi_app

    sock = bind_ephemeral_socket()
    port: int = sock.getsockname()[1]

    config = uvicorn.Config(
        fastapi_app,
        host=HOST,
        port=0,  # sockets 直传时此值不参与 bind，仅为满足 Config 签名
        log_config=_stderr_access_log_config(),
    )
    server = uvicorn.Server(config)

    # 先于 serve：端口已 listen，早到的连接在 backlog 里排队，不会丢
    _emit_ready(port)
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
