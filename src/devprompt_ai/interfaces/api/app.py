"""FastAPI 应用工厂：Web 形态唯一入口（业务单一来源 service.py，MUST-10）。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from devprompt_ai.common.process import ProcessError, ProcessTimeoutError
from devprompt_ai.config import AppConfig
from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.interfaces.api import routes
from devprompt_ai.interfaces.api.schemas import ApiResponse


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
    return app


app = create_app()
