"""JSON 提取当前行为的基线固化（Batch 0 决策门产物）。

这些用例记录**改动前**的真实行为，使 Batch 3 的 M-1 改动可被验证：
实施后 real 级样本应从「失败」转为「成功」。

来源：scripts/probe_json_extraction.py 的 8 类样本（2026-10-16 首轮执行）。
真实脆弱点 2 个 —— JSON 尾部带含花括号的解释文字、首个围栏块是说明文字。
顶层数组虽同样失败，但违反当前 prompt 约束（顶层必须 object），不作为依据。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from devprompt_ai.harness.llm import _parse_model

_PAYLOAD = '{"variants":[{"title":"x","body":"y","level":"A"}]}'
_ARRAY_PAYLOAD = '[{"title":"x","body":"y","level":"A"}]'


class _Variant(BaseModel):
    title: str
    body: str
    level: str


class _Multi(BaseModel):
    variants: list[_Variant]


def _ok(raw: str) -> bool:
    return _parse_model(_Multi, raw) is not None


class TestControlSamples:
    """对照样本：证明解析路径本身是通的（Batch 3 改动后仍须通过）。"""

    @pytest.mark.parametrize(
        ("name", "raw"),
        [
            ("纯 JSON 对象", _PAYLOAD),
            ("json 围栏包裹", f"```json\n{_PAYLOAD}\n```"),
            ("尾部解释文字不含花括号", _PAYLOAD + "\n\n以上为结果。"),
            (
                "字符串值内含右花括号且尾部无干扰",
                '{"variants":[{"title":"用 } 闭合","body":"嵌套 }","level":"A"}]}',
            ),
        ],
    )
    def test_parses(self, name: str, raw: str) -> None:
        assert _ok(raw), f"对照样本不应回归：{name}"


class TestRealVulnerabilities:
    """真实脆弱点：Batch 3 实施 M-1 后，这两条应转为成功。"""

    def test_trailing_prose_with_braces_fails_now(self) -> None:
        """LLM 常在 JSON 后追加说明，说明里带 {} 示例也很常见。"""
        raw = _PAYLOAD + '\n\n说明：取值如 {"level":"A"}。'
        assert not _ok(raw), "改动前应失败；若已通过说明 M-1 已实施，请更新本用例"

    def test_leading_prose_fence_fails_now(self) -> None:
        """首个围栏块是说明文字时，正则取了错的那个块。"""
        raw = "```\n分析：{}\n```\n```json\n" + _PAYLOAD + "\n```"
        assert not _ok(raw), "改动前应失败；若已通过说明 M-1 已实施，请更新本用例"


class TestKnownLimits:
    """已知边界：记录但当前不修（修复归属见计划 Batch 3）。"""

    def test_top_level_array_fails(self) -> None:
        """顶层数组被 greedy 截断成内层对象。

        项目全部 output_type 均为对象模型且 prompt 强制「顶层必须是 object」，
        故此路径当前不可达；数组支持归属 M-2 的候选生成，不在 M-1 范围内。
        """
        assert not _ok(_ARRAY_PAYLOAD)

    def test_truncated_output_fails(self) -> None:
        """模型输出被截断（未闭合）必然失败，由既有纠偏重试兜底。"""
        assert not _ok(_PAYLOAD[:-1])

    def test_non_json_text_fails(self) -> None:
        assert not _ok("抱歉，我无法完成该请求。")

    def test_empty_string_fails(self) -> None:
        assert not _ok("")


class TestProbeScriptContract:
    def test_probe_script_exists_and_separates_risk_levels(self) -> None:
        """探针脚本须保持可运行，且区分 real/fake 风险等级。"""
        from pathlib import Path

        script = Path(__file__).resolve().parents[1] / "scripts" / "probe_json_extraction.py"
        assert script.is_file(), "探针脚本缺失"
        source = script.read_text(encoding="utf-8")
        assert '"real"' in source and '"fake"' in source, "探针须区分 real/fake 风险等级"

    def test_probe_covers_eight_samples(self) -> None:
        """样本集被固化：数量变化须同步更新本文件与探针脚本。"""
        from pathlib import Path

        script = Path(__file__).resolve().parents[1] / "scripts" / "probe_json_extraction.py"
        source = script.read_text(encoding="utf-8")
        count = sum(1 for line in source.splitlines() if line.strip().startswith("Sample("))
        assert count == 8, "探针样本数变化时请同步更新本测试的用例"
