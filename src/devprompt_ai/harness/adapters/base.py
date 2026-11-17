"""原生协议 Model 子类的公共基类。

只承载**跨协议复用**的逻辑，不包含任何具体协议细节：

1. 构造期校验（model 名非空）——早失败优于请求期才报错；
2. `close()` 的幂等实现（`Model` 抽象提供 concrete 默认，此处显式覆写以支持重复调用）；
3. 诊断信息 `describe()`，供 smoke 脚本与日志输出「这个实例是什么形态」。

刻意**不**做的事：
- 不缓存响应（本地工具无此需求，且缓存 LLM 生成正文违反 MUST-14 精神）；
- 不在此处做参数清洗——那是 `domain/model_spec.apply_provider_constraints` 的职责。
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator
from typing import Any

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tool import Tool


def parse_image_data_url(data_url: str) -> tuple[str, str] | None:
    """解析 ``data:image/png;base64,....`` → (media_type, 纯 base64)；非法返回 None。

    供两个原生 adapter 把 agents 的 ``input_image`` item 转成各自协议的图像块
    （2026-11-14 多模态）。
    """
    prefix, sep, payload = data_url.partition(",")
    if not sep or not prefix.startswith("data:"):
        return None
    meta = prefix[5:]
    if ";base64" not in meta.lower():
        return None
    media_type = meta.split(";", 1)[0]
    return (media_type or "application/octet-stream"), payload


class BaseNativeModel(Model, ABC):
    """原生协议 Model 子类的公共基类。

    子类实现 `get_response` / `stream_response` 两个抽象方法（`Model` 仅此二者），
    Runner 的客户端工具循环、并行工具、流式事件映射全部由 SDK 复用。
    """

    def __init__(self, model: str, *, api_mode: str) -> None:
        if not model or not model.strip():
            raise ValueError("model 名不能为空")
        self._model = model.strip()
        #: 该实例服务的 API 形态（诊断用；实际请求路径由子类决定）
        self.api_mode = api_mode
        self._closed = False

    @property
    def model_name(self) -> str:
        return self._model

    def describe(self) -> str:
        """一行诊断信息（smoke 脚本与日志用）。"""
        return f"{type(self).__name__}(model={self._model!r}, api_mode={self.api_mode})"

    async def close(self) -> None:
        """幂等关闭（`Model.close` 是协程，覆写须保持一致）。"""
        self._closed = True

    async def get_response(  # noqa: D102 - 签名对齐 agents.models.interface.Model
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Tool],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        raise NotImplementedError

    def stream_response(  # noqa: D102
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Tool],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> AsyncIterator[Any]:
        raise NotImplementedError


__all__ = ["BaseNativeModel"]
