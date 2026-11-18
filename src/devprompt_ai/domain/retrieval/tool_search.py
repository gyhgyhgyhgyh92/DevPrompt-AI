"""补充检索工具的参数组装（domain 纯函数，零 I/O）。

生成阶段让模型自主补一次检索时用：模型给检索词 → 组装 ripgrep 参数 → 命中行裁剪。
放在 domain 是因为「参数怎么拼、结果怎么裁」是纯规则；进程由 harness 侧执行。
"""

from __future__ import annotations

from typing import Final

#: 单次检索返回的最大命中行数（与动作输出截断同量级，进上下文可控）。
MAX_SEARCH_HITS: Final[int] = 20
#: 单次检索超时（秒）。
SEARCH_TIMEOUT_S: Final[float] = 10.0
#: ripgrep 退出码：0=有命中，1=无命中（工具视为正常结果，不算失败）。
RG_EXIT_CODES: Final[frozenset[int]] = frozenset({0, 1})


def build_search_args(query: str, *, limit: int = MAX_SEARCH_HITS) -> list[str]:
    """把检索词组装成 ripgrep 参数。

    用固定字符串匹配（``--fixed-strings``）：模型给的是字面检索词，转正则会引入
    注入面，也让结果不可预期。
    """
    return ["rg", "--fixed-strings", "-n", "--max-count", str(limit), "-e", query, "."]


def render_hits(output: str, *, limit: int = MAX_SEARCH_HITS) -> str:
    """裁剪命中行；无命中给显式提示，避免模型把空输出当成「已查证」。"""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return "（无命中）"
    return "\n".join(lines[:limit])
