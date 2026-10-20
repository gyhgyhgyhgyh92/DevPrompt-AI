"""模型目录 I/O 能力声明（MUST-06：domain 只依赖 Protocol，实现在 harness/models_client.py）。

领域层在这里只声明「我需要知道厂商提供了哪些模型」——不关心它怎么来的：
HTTP 客户端、鉴权、超时、重试全在 harness 层。异常统一抛 :class:`CatalogFetchError`
（定义在 `domain/errors.py`），第三方异常不得穿透到服务层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RemoteModelInfo:
    """厂商模型清单里的一个模型（已归一化）。

    字段**只取官方文档已确认的部分**：
    - 绝大多数 OpenAI 兼容端点只保证 ``model_id``；
    - DeepSeek 官方《获取模型列表》额外给出展示名、上下文窗口、输出上限与
      推理强度档位（api-docs.deepseek.com/api/list-models）。

    查不到的字段一律留 ``None`` / 空元组——**不填占位默认值**：假窗口比不显示更糟，
    会让告警拿一个不存在的上限做判定（MUST-24b / F-921）。
    """

    model_id: str
    display_name: str = ""
    #: 输入窗口上限（绝对 token）；``None`` = 该端点未提供
    max_context_length: int | None = None
    #: 该端点给出的可选窗口档位；空元组 = 只能用标称值
    context_window_tiers: tuple[int, ...] = ()
    #: 该端点支持的推理强度档位（如 low/medium/high）；空元组 = 未知
    reasoning_efforts: tuple[str, ...] = ()


@runtime_checkable
class ModelCatalogFetcher(Protocol):
    """拉取某个厂商端点当前可用的模型清单。"""

    async def fetch(self, *, base_url: str, api_key: str, timeout: float) -> list[RemoteModelInfo]:
        """返回该端点的模型清单。

        端点不支持 / 鉴权失败 / 限流 / 超时一律抛
        :class:`~devprompt_ai.domain.errors.CatalogFetchError`，且 ``message``
        必须是**可直接展示给用户的中文原因**（不得含 api_key 或响应全文，MUST-19）。
        """
        ...
