"""F-402 排名域端口：方案特征类型 + L3 偏好存储契约（MUST-06 Protocol 落点）。

实现在 memory/preference_store.py（5D SQLitePreferenceStore），由 service 组装注入；
本文件只声明能力，零 I/O。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, runtime_checkable

VariantLevel: TypeAlias = Literal["A", "B", "C"]

VariantFeatures: TypeAlias = dict[
    Literal["detail_level", "include_diff", "specify_tests", "max_files_norm"],
    float,
]


@dataclass(frozen=True, slots=True)
class AdoptionRecord:
    """F-503 采纳记录：5F service.feedback 产出，5D 落库。

    edited_text_ratio ∈ [0, 1] 为编辑距离占比，非编辑采纳固定 0。
    """

    user_id: str
    session_id: str
    variant: VariantLevel
    edited: bool
    edited_text_ratio: float
    features: VariantFeatures


@runtime_checkable
class PreferenceStore(Protocol):
    """L3 偏好向量读写契约（F-402/F-503）。"""

    async def load(self, user_id: str) -> dict[str, float]: ...

    async def save(self, user_id: str, vector: dict[str, float]) -> None: ...

    async def record_adoption(self, rec: AdoptionRecord) -> None: ...

    async def clear_adoptions(self, user_id: str) -> int:
        """清空该用户全部采纳历史（D-6F-4），返回清空条数；偏好向量不受影响。"""
        ...
