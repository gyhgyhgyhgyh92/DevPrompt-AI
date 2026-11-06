"""provider 目录的双语展示名（2026-11-06，F-209）。

中文 label 走英文映射表（品牌名保留可识别性），未登记映射的保持原样；
``quirks`` 仍是中文说明（功能清单 F-209 已登记为限制）。
"""

from __future__ import annotations

from devprompt_ai.domain.model_spec import PROVIDER_SPECS, providers_projection


def test_chinese_labels_have_english_mapping() -> None:
    zh = {p["id"]: p for p in providers_projection("zh-CN")}
    en = {p["id"]: p for p in providers_projection("en")}
    assert zh["dashscope"]["label"] == "阿里通义（百炼）"
    assert en["dashscope"]["label"] == "Aliyun Tongyi (Bailian)"
    assert zh["zhipu"]["label"] == "智谱 GLM"
    assert en["zhipu"]["label"] == "Zhipu GLM"


def test_english_label_never_leaks_chinese_for_mapped_entries() -> None:
    mapped = 0
    for item in providers_projection("en"):
        label = item["label"]
        if any("\u4e00" <= ch <= "\u9fff" for ch in label):
            # 未映射的（如纯英文品牌）允许保留，中文残留必须为 0
            raise AssertionError(f"{item['id']} 的英文 label 仍含中文：{label}")
        mapped += 1
    assert mapped == len(PROVIDER_SPECS)


def test_default_locale_unchanged() -> None:
    """默认语言与显式 zh-CN 完全一致（旧调用零改动）。"""
    assert [p["label"] for p in providers_projection()] == [
        p["label"] for p in providers_projection("zh-CN")
    ]


def test_quirks_are_translated_for_english() -> None:
    """11 段 quirks 说明在英文下有对应文案，且默认语言仍是原文（F-209 限制已解除）。"""
    zh = {p["id"]: p for p in providers_projection("zh-CN")}
    en = {p["id"]: p for p in providers_projection("en")}

    assert "x-api-key" in zh["anthropic"]["quirks"]
    assert "x-api-key" in en["anthropic"]["quirks"]
    assert zh["anthropic"]["quirks"] != en["anthropic"]["quirks"]

    # 所有带 quirks 的 provider 在英文下都不应残留中文
    for provider_id, item in en.items():
        if not item["quirks"]:
            continue
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in item["quirks"]), (
            f"{provider_id} 的英文 quirks 仍含中文：{item['quirks']}"
        )


def test_untouched_quirks_fall_back_to_chinese() -> None:
    """未登记英文映射的 provider 回落中文原文（不返回空串）。"""
    for item in providers_projection("en"):
        if item["quirks"]:
            assert item["quirks"].strip() != ""
