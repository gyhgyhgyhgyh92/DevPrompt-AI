"""ASGI 入口再导出与 `devprompt-ai` console script（MUST-10：业务与配置单一来源）。

本文件**不持有任何业务逻辑**，只承担两件事：

1. `app` —— 惰性再导出 `interfaces.api.app` 已创建的实例，供
   `uvicorn devprompt_ai.main:app` 引用。刻意**不**调用 `create_app()`：
   重复创建会产生第二个实例，使 CORS 中间件、异常处理器与 `X-Request-ID`
   中间件状态分裂，直接违反「状态单一/ 配置单一」。

2. `main()` —— `[project.scripts] devprompt-ai` 的实现：解析参数后交给 uvicorn。
   uvicorn 与 app 均惰性导入，使 `--help` 等轻量调用不触发 `AppConfig.validate()`
   （配置缺失时直接快速失败，但不该让打印帮助也失败）。
"""

from __future__ import annotations

import argparse
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["app", "main"]  # noqa: F822 —— app 由 PEP 562 惰性提供，静态分析看不到绑定

#: 默认监听配置：仅本机回环（本地工具形态，MUST-10），端口取 FastAPI/uvicorn 惯例 8000
#: ——**须与 frontend/vite.config.ts 的 dev proxy 目标一致**，否则前端联调打不到后端。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def __getattr__(name: str) -> FastAPI:
    """PEP 562 模块级惰性属性：仅在真正访问 `devprompt_ai.main.app` 时导入实例。

    未知名抛`AttributeError` 而非静默返回，保留标准模块语义。
    """
    if name == "app":
        from devprompt_ai.interfaces.api.app import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数（argparse 标准库，MUST-04 第 2 级）。"""
    parser = argparse.ArgumentParser(
        prog="devprompt-ai",
        description="DevPrompt AI 本地服务（单端口托管前端 dist，架构文档 §1.5）",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"监听地址（默认 {DEFAULT_HOST}；0.0.0.0 表示对外暴露）",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）"
    )
    parser.add_argument("--reload", action="store_true", help="开发模式：源码变更自动重载")
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="启动后自动用默认浏览器打开",
    )
    return parser.parse_args(argv)


def _display_url(host: str, port: int) -> str:
    """构造可点击的展示 URL：`0.0.0.0` / `::` 是监听通配地址，不是可导航主机名。"""
    navigable = "localhost" if host in ("0.0.0.0", "::", "") else host
    return f"http://{navigable}:{port}"


def main(argv: list[str] | None = None) -> int:
    """console script 入口：参数收拢 → 启动 uvicorn。返回进程退出码。

    传入应用字符串而非 app 对象：与 `--reload` 兼容（reload 需可重导入的模块路径）。
    """
    args = _parse_args(argv)

    import uvicorn

    url = _display_url(args.host, args.port)
    print(f"DevPrompt AI 启动中 → {url}（Ctrl+C 停止）")
    if args.open_browser:
        webbrowser.open(url)
    uvicorn.run(
        "devprompt_ai.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0
