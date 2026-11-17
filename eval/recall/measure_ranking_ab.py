"""W3 排序评测 A/B 对照（同模型同环境）：签名开 / 关。

背景：2026-11-05 MUST-09 改造给候选附了 ≤1 行函数签名。要回答「签名是否真提升排序」，
必须同模型同环境 A/B——跨时间对比（对 2026-10-11 的 58% 基线）会混入模型与环境差异。

用法（仓库根执行）：

    uv run python eval/recall/measure_ranking_ab.py --all                  # 带签名（现状代码）
    uv run python eval/recall/measure_ranking_ab.py --all --no-signature --out eval/recall/ab-no-sig

原理：``--no-signature`` 把 ``harness.process`` 里绑定的 ``build_ctags_args`` 换成
``with_signature=False`` 版本。ctags 不吐 signature 字段 → JSON 行无该键 →
``parse_ctags_output`` 得空串 → 候选 listing 自动省略签名行，即改造前行为。
其余链路（评测语料、模型、超时、门禁判定）与带签名版完全一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _disable_signature() -> None:
    """把 harness 侧绑定的 ctags 参数构造器换成无签名版本（运行时 patch）。"""
    import devprompt_ai.harness.process as process_mod
    from devprompt_ai.domain.retrieval.symbols import build_ctags_args

    def without_signature(project_root: str) -> list[str]:
        return build_ctags_args(project_root, with_signature=False)

    process_mod.build_ctags_args = without_signature  # type: ignore[assignment]


def main() -> int:
    if "--no-signature" in sys.argv:
        sys.argv.remove("--no-signature")
        _disable_signature()
    import measure_ranking  # noqa: PLC0415 - 必须在 patch 生效后导入并调用

    return measure_ranking.main()


if __name__ == "__main__":
    raise SystemExit(main())
