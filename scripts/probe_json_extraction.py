"""探针：验证当前 JSON 提取实现的脆弱点是否真实存在（Batch 0 决策门）。

为什么需要：M-1 计划用「括号配平状态机」替换 `_extract_json` 的首尾贪心截取，
但该脆弱性尚未经实测确认。若真实场景下不会触发，这 50 行代码与一个长期维护点
就是纯负担（YAGNI）。本脚本离线运行，无需 API Key。

当前实现（src/devprompt_ai/harness/llm.py:46-55）：取第一个左括号到最后一个
右括号。该假设仅在「输出恰好是一个对象、且尾部无任何右括号」时成立。

风险等级（首轮执行时修正过一次，见 Sample 5 注释）：
- real= 真实路径上会发生，LLM 确实会这样输出
- fake   = 构造性失败，违反当前 prompt 约束（顶层必须 object），不会真实发生
- 对照样本用于校准：证明解析路径本身是通的

退出码：0 = 存在真实脆弱点（应实施 M-1）；1 = 无真实脆弱点（M-1 应降级）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import BaseModel  # noqa: E402

from devprompt_ai.harness.llm import _parse_model  # noqa: E402


class _Variant(BaseModel):
    """与 domain.generate.ports.VariantDraft 同形，仅用于走通校验路径。"""

    title: str
    body: str
    level: str


class _Multi(BaseModel):
    variants: list[_Variant]


_PAYLOAD = '{"variants":[{"title":"x","body":"y","level":"A"}]}'
_ARRAY_PAYLOAD = '[{"title":"x","body":"y","level":"A"}]'


@dataclass(frozen=True)
class Sample:
    index: int
    name: str
    raw: str
    risk: str
    """real= 真实脆弱点（预期失败）；fake = 构造性失败；control = 对照（预期成功）。"""


SAMPLES: tuple[Sample, ...] = (
    Sample(1, "纯 JSON 对象", _PAYLOAD, "control"),
    Sample(2, "json 围栏包裹", f"```json\n{_PAYLOAD}\n```", "control"),
    Sample(3, "JSON 后有解释文字且含花括号", _PAYLOAD + '\n\n说明：取值如 {"level":"A"}。', "real"),
    Sample(4, "JSON 后有解释文字但不含花括号", _PAYLOAD + "\n\n以上为结果。", "control"),
    # 顶���数组：项目全部 output_type 均为对象模型，且 prompt 强制「顶层必须是 object」，
    # 故该失败违反当前约束、不会在真实路径发生。保留样本仅为说明 greedy 假设的边界。
    Sample(5, "顶层数组（违反 prompt 约束）", _ARRAY_PAYLOAD, "fake"),
    Sample(
        6,
        "字符串值内含右花括号且尾部无干扰",
        '{"variants":[{"title":"用 } 闭合","body":"嵌套 }","level":"A"}]}',
        "control",
    ),
    Sample(
        7,
        "两个围栏块，第一个是说明文字",
        "```\n分析：{}\n```\n```json\n" + _PAYLOAD + "\n```",
        "real",
    ),
    Sample(8, "JSON 未闭合（输出被截断）", _PAYLOAD[:-1], "control"),
)


def main() -> int:
    rows: list[tuple[int, str, str, str]] = []
    real_failed: list[str] = []
    for sample in SAMPLES:
        parsed = _parse_model(_Multi, sample.raw)
        ok = parsed is not None
        if sample.risk == "real" and not ok:
            real_failed.append(sample.name)
        verdict = "成功" if ok else "失败"
        rows.append((sample.index, sample.name, verdict, sample.risk))

    width = max(len(name) for _, name, _, _ in rows) + 2
    print(f"{'#':<3}{'样本':<{width}}{'当前实现':<8}风险等级")
    print("-" * (width + 20))
    for index, name, verdict, risk in rows:
        print(f"{index:<3}{name:<{width}}{verdict:<8}{risk}")

    print()
    if real_failed:
        print(f"存在真实脆弱点 {len(real_failed)} 个：")
        for name in real_failed:
            print(f"  - {name}")
        print("→ Batch 3 应全量实施 M-1（括号配平状态机）")
        return 0
    print("无真实脆弱点：所有 real 级样本均解析成功")
    print("→ M-1 应降级为「仅加注释说明已知限制」，不实施 50 行状态机")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
