"""FastAPI 应用工厂：Web 形态唯一入口（业务单一来源 service.py，MUST-10）。"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from devprompt_ai.common.process import ProcessError, ProcessTimeoutError
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.interfaces.api import routes
from devprompt_ai.interfaces.api.schemas import ApiResponse


class _SpaStaticFiles(StaticFiles):
    """前端构建产物的单端口静态托管 + SPA 回退（基础设施，非业务逻辑，MUST-10 允许）。

    未匹配到的非 `/api` 路径回退 `index.html`，供前端 BrowserRouter 深链接直达；
    `/api` 前缀不参与回退（缺失 API 仍 404，避免遮蔽契约错误）。
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # path 经 os.path.normpath 归一（Windows 下分隔符为 `\`），跨平台统一判断
            normalized = path.replace("\\", "/").strip("/")
            is_api = normalized == "api" or normalized.startswith("api/")
            if exc.status_code == 404 and not is_api:
                return await super().get_response("index.html", scope)
            raise


def _frontend_dist() -> Path | None:
    """定位前端构建产物目录；缺失返回 None（跳过挂载，不影响既有 API/测试）。"""
    candidates: list[Path] = []
    override = os.environ.get("DEVPROMPT_FRONTEND_DIST")
    if override:
        candidates.append(Path(override).expanduser())
    # 源码/可编辑安装：仓库根 = src/devprompt_ai/interfaces/api/app.py 上溯 4 层
    candidates.append(Path(__file__).resolve().parents[4] / "frontend" / "dist")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


#: 指纹化静态资源的缓存时长（秒）。Vite 产物带内容哈希，内容变则文件名变，
#: 故可安全地长期强缓存；入口 HTML 必须每次回源，否则会锁死在旧版本引用上。
_ASSET_MAX_AGE_SECONDS = 604800  # 7 天

#: 入口 HTML 与根路径的缓存指令：no-store 确保发版后立即生效
_NO_STORE = "no-store, no-cache, must-revalidate"


async def _add_cache_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """按「静态资源长缓存 / 入口 HTML 禁缓存」分流（M-11）。

    借鉴 prompt-optimizer 的 nginx 配置：`/assets` 带内容指纹 → 长缓存；
    `index.html` 与 `/` → `no-store`。缺失这一步会导致**发版后用户仍加载旧 JS**。
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = f"public, max-age={_ASSET_MAX_AGE_SECONDS}, immutable"
    elif path in ("/", "/index.html"):
        response.headers["Cache-Control"] = _NO_STORE
    return response


async def _add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """基础安全响应头（M-11）。

    刻意**不加 CSP**：Vite 产物含内联样式/脚本，过严的 CSP 会直接白屏；
    也不加 HSTS——本项目是本地工具 served over HTTP，加了反而误导。
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _error_code(exc: Exception) -> int:
    """错误码映射：领域/子进程异常取其 code；超时类统一 5001（原 CLI 渲染语义平移）。"""
    if isinstance(exc, DevPromptError):
        return exc.code
    if isinstance(exc, ProcessError):
        return exc.code
    return 5001


async def _render_error(request: Request, exc: Exception) -> JSONResponse:
    """统一错误渲染：仅 code + message + request_id，不回传堆栈（MUST-19）。"""
    body: ApiResponse[None] = ApiResponse(
        code=_error_code(exc), message=str(exc), request_id=uuid.uuid4().hex
    )
    return JSONResponse(status_code=500, content=body.model_dump())


def create_app() -> FastAPI:
    cfg = AppConfig()
    cfg.validate()
    app = FastAPI(title="DevPrompt AI", version="0.1.0")
    origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """X-Request-ID 全端点透传（§3.1）：回显请求头或生成，信封 request_id 取同一值。"""
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(routes.router)
    for exc_type in (DevPromptError, ProcessError, ProcessTimeoutError, TimeoutError):
        app.add_exception_handler(exc_type, _render_error)
    # py3.10 下 asyncio.TimeoutError 与内建 TimeoutError 非同一类，显式覆盖
    app.add_exception_handler(asyncio.TimeoutError, _render_error)
    # M-11 响应头：注册在路由之后，故对 SPA 回退与静态资源同样生效
    app.middleware("http")(_add_cache_headers)
    app.middleware("http")(_add_security_headers)

    # 单端口托管：dist 存在时挂载于最后，/api/v1/* 与应用内建路由（docs/openapi）先行匹配（MUST-10）
    dist = _frontend_dist()
    if dist is not None:
        app.mount("/", _SpaStaticFiles(directory=str(dist), html=True), name="spa")
    return app


app = create_app()
