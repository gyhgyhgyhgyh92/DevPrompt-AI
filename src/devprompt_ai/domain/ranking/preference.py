"""F-402 偏好向量：方案特征表 + 匹配度计算（纯逻辑零 I/O，MUST-06/MUST-08）。"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.ranking.ports import VariantFeatures, VariantLevel

# F-402「方案特征向量」原文逐值（2026-10-10 逐维核对）。
# 注意：实施计划初稿的「0.25/0.58/1.0」仅为 max_files_norm 单行归一化值，
# 并非各档全维取值——已按功能清单原文分维实现（D-5B-1 类上报点，见任务报告）。
# 归一化规则：max_files_norm = max_files / 4（原值 A=1 / B=2.3 / C=4 个文件）。
FEATURE_TABLE: Final[dict[VariantLevel, VariantFeatures]] = {
    "A": {
        "detail_level": 0.3,
        "include_diff": 0.5,
        "specify_tests": 0.2,
        "max_files_norm": 0.25,
    },
    "B": {
        "detail_level": 0.6,
        "include_diff": 0.8,
        "specify_tests": 0.5,
        "max_files_norm": 0.58,
    },
    "C": {
        "detail_level": 0.9,
        "include_diff": 0.9,
        "specify_tests": 0.8,
        "max_files_norm": 1.0,
    },
}

# F-402 初始值：全部维度 0.5（中性），无历史数据时不影响排序。
INITIAL_PREFERENCE: Final[dict[str, float]] = {
    "detail_level": 0.5,
    "include_diff": 0.5,
    "specify_tests": 0.5,
    "max_files_norm": 0.5,
}

# pref 缺维度按中性值 0.5 补（F-402「无历史数据时不影响排序」的等价实现）。
NEUTRAL_DIM: Final[float] = 0.5


def clip01(x: float) -> float:
    """截断到 [0, 1]：浮点误差与超界输入的统一防线。"""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def match_score(pref: dict[str, float], feat: VariantFeatures) -> float:
    """F-402 偏好匹配度：1 - mean(|pref_i - feat_i|)，四维均已归一化到 [0, 1]。

    pref 缺维度按 0.5（中性）补齐，保证无历史数据时匹配度仍可计算且不影响流程。
    """
    diffs = [abs(pref.get(key, NEUTRAL_DIM) - value) for key, value in feat.items()]
    return clip01(1.0 - sum(diffs) / len(diffs))
