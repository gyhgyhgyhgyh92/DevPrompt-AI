"""可观测性路由公共装配（三模块共享的薄壳工具）。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from devprompt_ai.domain.errors import DevPromptError
from devprompt_ai.interfaces.api.routes import get_service
from devprompt_ai.interfaces.api.runtime_routes import _request_id
from devprompt_ai.obs.registry import ObsModules, build_obs_modules


async def obs_modules() -> ObsModules:
    """懒加载模块集合；ForgeService 构建时已注入则直接复用（避免双采集器）。"""
    service = await get_service()
    modules = getattr(service, "obs", None)
    if isinstance(modules, ObsModules):
        return modules
    modules = build_obs_modules(service.config)
    service.obs = modules
    await modules.startup()
    return modules


def require_enabled(module: Any, name: str) -> Any:
    if not getattr(module, "enabled", False):
        raise DevPromptError(f"可观测性模块未启用：{name}", code=6004, context={"module": name})
    return module


def request_id_of(request: Request) -> str:
    return _request_id(request, None)
