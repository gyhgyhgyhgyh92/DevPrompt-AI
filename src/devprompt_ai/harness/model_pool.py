"""客户端池（G1）：按 (model, base_url, api_key) 复用连接，LRU 上限 4。

此前是单个全局 client：切一次模型就重建一次，两个会话交替用不同模型时反复
新建客户端、连接池反复失效。池化后同模型复用，切回旧模型也不重建。
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

T = TypeVar("T")


class ModelPool(Generic[T]):
    def __init__(self, factory: Callable[[Hashable], T], *, capacity: int = 4) -> None:
        self._factory = factory
        self._capacity = max(1, capacity)
        self._items: OrderedDict[Hashable, T] = OrderedDict()

    def get(self, key: Hashable) -> T:
        existing = self._items.get(key)
        if existing is not None:
            self._items.move_to_end(key)
            return existing
        client = self._factory(key)
        self._items[key] = client
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)
        return client

    def keys(self) -> list[Hashable]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()
