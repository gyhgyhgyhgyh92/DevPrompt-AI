"""模型目录（纯领域，零 I/O）：端口见 `ports.py`，合并回落见 `catalog.py`。

领域层只声明「需要知道厂商提供了哪些模型」与「怎么把多来源窗口合成一条回落链」，
不接触 HTTP、不接触 SQLite——实现分别在 `harness/models_client.py` 与
`memory/model_catalog_store.py`，由 `service` 组装时注入（MUST-06）。
"""

from devprompt_ai.domain.model_catalog.catalog import (
    CatalogSource,
    ModelCatalogItem,
    effective_context_window,
    find_item,
    mark_stale_models,
    merge_catalog,
    static_catalog,
)
from devprompt_ai.domain.model_catalog.ports import ModelCatalogFetcher, RemoteModelInfo

__all__ = (
    "CatalogSource",
    "ModelCatalogFetcher",
    "ModelCatalogItem",
    "RemoteModelInfo",
    "effective_context_window",
    "find_item",
    "mark_stale_models",
    "merge_catalog",
    "static_catalog",
)
