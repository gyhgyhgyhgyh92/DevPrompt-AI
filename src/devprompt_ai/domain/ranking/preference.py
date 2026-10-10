"""F-402 偏好向量：方案特征表 + 匹配度计算（纯逻辑零 I/O，MUST-06/MUST-08）。"""

from __future__ import annotations

from typing import Final

from devprompt_ai.domain.ranking.ports import AdoptionRecord, VariantFeatures, VariantLevel

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


# ---- F-503 偏好更新（开放决策 #1 定稿合成语义，用户裁定 2026-10-10）----

# F-503「滑动平均，衰减系数 0.9」：EMA 残余权重，步进 = 1 − 0.9 = 0.1。
EMA_DECAY: Final[float] = 0.9
EMA_STEP: Final[float] = 1.0 - EMA_DECAY
# F-503「直接采纳 +1.0」为信号强度语义（非向量字面加 1.0）：强度 1.0 = 完整 EMA 步进。
ADOPT_SIGNAL: Final[float] = 1.0
# 开放决策 #1：跳过趋向中性系数 0.3（独立规则，不经 EMA——D-5D-1 张力由本裁定消解）。
SKIP_REGRESSION: Final[float] = 0.3


def update_vector(v: dict[str, float], rec: AdoptionRecord | None) -> dict[str, float]:
    """F-503 隐式反馈更新偏好向量（纯函数，不修改入参；store 只做 I/O，MUST-06/MUST-08）。

    合成语义（开放决策 #1 定稿，2026-10-10）：
    - rec 为采纳（edited_text_ratio=0）：v ← 0.9v + 0.1×feat，向该方案特征值移动；
    - rec 为编辑采纳：同一 EMA、观测权重按信号强度缩放
      v ← v + 0.1×(1−edited_text_ratio)×(feat−v)；
      强度=1 时退化为采纳公式，强度→0（完全重写）时向量不动——重写不产生方向信号；
    - rec 为 None（跳过全部方案）：v ← v + (0.5−v)×0.3，趋向中性，收敛不过冲；
    - 输出逐维 clip01（F-503「上下限裁剪在 [0, 1]」，对超界输入同样设防）。
    缺维度按中性值 0.5 补（与 INITIAL_PREFERENCE 一致）。
    """
    out = dict(v)
    if rec is None:
        for dim in INITIAL_PREFERENCE:
            cur = out.get(dim, NEUTRAL_DIM)
            out[dim] = clip01(cur + (NEUTRAL_DIM - cur) * SKIP_REGRESSION)
        return out
    strength = ADOPT_SIGNAL * (1.0 - rec.edited_text_ratio)
    for dim, feat in rec.features.items():
        cur = out.get(dim, NEUTRAL_DIM)
        out[dim] = clip01(cur + EMA_STEP * strength * (feat - cur))
    return out
