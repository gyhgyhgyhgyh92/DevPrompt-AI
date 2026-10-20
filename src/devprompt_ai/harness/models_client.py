"""模型目录拉取实现（MUST-06：实现属于 harness/，领域层只声明 Protocol）。

**为什么复用 openai SDK 而不是自己发 HTTP**：OpenAI 兼容协议里模型清单就是
`GET {base_url}/models`，SDK 的 `models.list()` 自带超时、重试语义与连接池；复用它
等于**零新依赖**（MUST-04 优先级第 4 级）。

**字段只认官方文档已确认的**（MUST-24b，不得凭印象）：
- 标准：`id`（OpenAI 兼容协议保证）；
- DeepSeek 扩展（api-docs.deepseek.com/api/list-models）：`name`（展示名）、
  `context_window`、`effort.supported_levels`；
- **窗口档位**：DeepSeek 未提供可选档位字段，故 `context_window_tiers` 恒空——
  不猜字段名，查不到就交回领域层回落静态表。

错误一律转成 :class:`CatalogFetchError`，``message`` 是可直接展示的中文原因；
**不记录 api_key、不记录响应全文**（MUST-19）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from devprompt_ai.domain.errors import CatalogFetchError
from devprompt_ai.domain.model_catalog.ports import RemoteModelInfo

#: 外部调用默认超时（MUST-13：每个外部调用必须设超时）
DEFAULT_TIMEOUT: Final[float] = 10.0

#: DeepSeek《Lists Models》确认的扩展字段名。改动前先核对官方文档。
_FIELD_CONTEXT_WINDOW: Final[str] = "context_window"
_FIELD_DISPLAY_NAME: Final[str] = "name"
_FIELD_EFFORT: Final[str] = "effort"
_FIELD_EFFORT_LEVELS: Final[str] = "supported_levels"


def _as_int(value: Any) -> int | None:
    """只接受正整数；字符串数字也接受（供应商字段类型不稳）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def parse_model_entry(entry: Any) -> RemoteModelInfo | None:
    """把一条 `/models` 响应解析成 :class:`RemoteModelInfo`。

    :returns: ``None`` 表示该条没有可用 ``id``（畸形条目，调用方直接丢弃）
    """
    if isinstance(entry, dict):
        data: dict[str, Any] = entry
    elif hasattr(entry, "model_dump"):
        dumped = entry.model_dump()
        data = dumped if isinstance(dumped, dict) else {}
    else:
        data = {}

    model_id = str(data.get("id") or "").strip()
    if not model_id:
        return None

    effort = data.get(_FIELD_EFFORT)
    levels = effort.get(_FIELD_EFFORT_LEVELS) if isinstance(effort, dict) else None

    return RemoteModelInfo(
        model_id=model_id,
        display_name=str(data.get(_FIELD_DISPLAY_NAME) or "").strip(),
        max_context_length=_as_int(data.get(_FIELD_CONTEXT_WINDOW)),
        # DeepSeek 未提供窗口档位字段 → 空元组，由领域层回落静态表
        context_window_tiers=(),
        reasoning_efforts=_as_str_tuple(levels),
    )


def parse_models_response(payload: Any) -> list[RemoteModelInfo]:
    """解析 `/models` 完整响应体（``{"data": [...]}``）；畸形结构返回空列表。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    entries = [parse_model_entry(item) for item in data]
    return [item for item in entries if item is not None]


def _describe(exc: BaseException) -> str:
    """把 SDK 异常翻译成用户能看懂的中文原因（不含密钥与响应全文）。"""
    if isinstance(exc, AuthenticationError):
        return "鉴权失败：请检查该条目的 API Key 是否正确"
    if isinstance(exc, RateLimitError):
        return "服务商限流：请稍后重试刷新模型列表"
    if isinstance(exc, NotFoundError):
        return "该服务商未提供模型列表接口（GET /models），请改用已登记的模型"
    if isinstance(exc, APITimeoutError | asyncio.TimeoutError):
        return "拉取模型列表超时：请检查网络或稍后重试"
    if isinstance(exc, APIConnectionError):
        return "无法连接该服务端点：请检查接口地址与网络"
    if isinstance(exc, APIStatusError):
        return f"服务商返回错误状态（HTTP {exc.status_code}）：请检查接口地址是否正确"
    return f"拉取模型列表失败：{type(exc).__name__}"


class OpenAIModelsFetcher:
    """`ModelCatalogFetcher` 的 openai SDK 实现。"""

    async def fetch(
        self, *, base_url: str, api_key: str, timeout: float = DEFAULT_TIMEOUT
    ) -> list[RemoteModelInfo]:
        """拉取模型清单；任何失败都抛 :class:`CatalogFetchError`（message 可直接展示）。

        :param api_key: 仅在内存中用于本次请求，**不落盘、不进日志**（MUST-19）。
        """
        if not base_url.strip():
            raise CatalogFetchError("该条目未填写接口地址，无法拉取模型列表")
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "EMPTY",
            timeout=timeout,
            max_retries=0,  # 刷新是用户显式动作，重试只会让「点了没反应」
        )
        try:
            response = await client.models.list()
        except (
            AuthenticationError,
            RateLimitError,
            NotFoundError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
            asyncio.TimeoutError,
        ) as exc:
            # 子类必须在 APIStatusError 之前列出（否则细分原因会被父类吞掉）；
            # 具体归类由 _describe 的 isinstance 顺序决定。
            raise CatalogFetchError(_describe(exc)) from exc
        finally:
            await client.close()

        models = parse_models_response(response.model_dump())
        if not models:
            raise CatalogFetchError("该服务端点返回了空的模型列表")
        return models
