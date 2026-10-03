"""领域模型。"""

from dataclasses import dataclass


@dataclass
class User:
    """用户实体。"""

    id: int
    name: str


@dataclass
class OrderItem:
    """订单条目实体。"""

    order_id: int
    sku: str
    qty: int
