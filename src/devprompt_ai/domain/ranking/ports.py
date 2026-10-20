"""F-402 排名域端口：方案特征类型 + L3 偏好存储契约（MUST-06 Protocol 落点）。

实现在 memory/preference_store.py（5D SQLitePreferenceStore），由 service 组装注入；
本文件只声明能力，零 I/O。
"""

from __future__ import annotations

from typing import Literal, TypeAlias

VariantLevel: TypeAlias = Literal["A", "B", "C"]

VariantFeatures: TypeAlias = dict[
    Literal["detail_level", "include_diff", "specify_tests", "max_files_norm"],
    float,
]


