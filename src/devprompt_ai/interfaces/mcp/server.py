"""把优化能力暴露为 MCP Server（2026-11-21）。

只做「参数收拢 → 调 ForgeService → 渲染文本」，不复制任何业务判定：
方案生成、推荐标记、澄清全部仍在 service 层，两个交付形态共用同一实现。

启动：
    devprompt-ai-mcp                 # 默认 stdio，给 Claude Desktop 等本地客户端
    devprompt-ai-mcp --transport streamable-http --port 8765
"""

from __future__ import annotations

import argparse
import uuid
from collections.abc import Awaitable, Callable

from mcp.server.mcpserver import MCPServer

from devprompt_ai.config import AppConfig
from devprompt_ai.service import FlowSnapshot, ForgeService, build_default

ServiceFactory = Callable[[], Awaitable[ForgeService]]

_instructions = (
    "DevPrompt AI：把模糊的自然语言需求编译为工程级提示词/改动方案，"
    "先检索真实代码取证再生成，必要时反问。"
)


def render_snapshot(snapshot: FlowSnapshot) -> str:
    """把快照渲染成 MCP 纯文本：状态 + 需要确认项 + 方案正文。"""
    lines = [f"状态：{snapshot.status} / {snapshot.state}"]
    if snapshot.target is not None:
        lines.append(f"目标：{snapshot.target.name} @ {snapshot.target.path}:{snapshot.target.line}")
    if snapshot.questions:
        lines.append("需要确认：")
        lines.extend(f"- {item.ask}" for item in snapshot.questions)
    if snapshot.variant is not None:
        lines.append(f"## {snapshot.variant.title}\n{snapshot.variant.body}")
    if snapshot.message:
        lines.append(str(snapshot.message))
    lines.append(f"会话：{snapshot.session_id}（继续追问时带上它）")
    return "\n\n".join(lines)


def build_server(service_factory: ServiceFactory | None = None) -> MCPServer:
    """构造 MCP Server；`service_factory` 供测试注入替身。"""
    cache: dict[str, ForgeService] = {}

    async def _service() -> ForgeService:
        if service_factory is not None:
            return await service_factory()
        if "svc" not in cache:
            cfg = AppConfig()
            cfg.validate()
            cache["svc"] = await build_default(cfg)
        return cache["svc"]

    server = MCPServer(name="devprompt-ai", instructions=_instructions)

    @server.tool(
        name="optimize_prompt",
        description="把一句模糊需求编译为可执行的工程级提示词；需要时返回待确认问题。",
    )
    async def optimize_prompt(
        requirement: str,
        project_root: str = "",
        locale: str = "zh-CN",
        session_id: str = "",
    ) -> str:
        svc = await _service()
        snapshot: FlowSnapshot = await svc.optimize(
            "local",
            project_root,
            requirement,
            request_id=uuid.uuid4().hex,
            session_id=session_id or uuid.uuid4().hex,
            create_session=True,
            locale="en" if locale.lower().startswith("en") else "zh-CN",
        )
        return render_snapshot(snapshot)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="devprompt-ai-mcp", description="DevPrompt AI MCP Server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio 供本地客户端拉起；streamable-http 供远程接入",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = build_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover - 进程入口
    main()
