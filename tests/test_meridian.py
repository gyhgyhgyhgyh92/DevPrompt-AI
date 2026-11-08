"""Meridian 测试：AST 符号图、影响半径、BM25/RRF、路径重排与访问强化。"""

from __future__ import annotations

from devprompt_ai.domain.retrieval.bm25 import BM25Index, rrf, tokenize
from devprompt_ai.domain.retrieval.impact import compute_impact, requires_verification
from devprompt_ai.domain.retrieval.physarum import decay, prune, reinforce
from devprompt_ai.domain.retrieval.salience import path_weight, rerank
from devprompt_ai.harness.pygraph import import_edges, parse_python

_SOURCE = """
import os
from package import helper


def top(a, b):
    return helper(a)


class Service:
    def run(self):
        return top(1, 2)
"""


def test_parse_python_symbols_imports_calls() -> None:
    parsed = parse_python("pkg/mod.py", _SOURCE)

    names = {symbol.name: symbol.kind for symbol in parsed.symbols}
    assert names == {"top": "function", "Service": "class", "run": "method"}
    assert "os" in parsed.imports and "package" in parsed.imports
    assert "helper" in parsed.calls and "top" in parsed.calls
    assert parsed.errors == ()

    top = next(symbol for symbol in parsed.symbols if symbol.name == "top")
    assert top.signature.startswith("top(a, b)")
    assert top.end_line >= top.line


def test_parse_python_handles_syntax_error() -> None:
    parsed = parse_python("bad.py", "def broken(:\n")

    assert parsed.symbols == ()
    assert parsed.errors and parsed.errors[0].startswith("syntax:")


def test_import_edges_resolve_known_paths() -> None:
    parsed = parse_python("pkg/mod.py", "import package\n")

    edges = import_edges(parsed, {"package/__init__.py", "other.py"})

    assert edges == [("pkg/mod.py", "package/__init__.py")]


def test_impact_bfs_hops_and_limit() -> None:
    reverse = {"a.py": {"b.py"}, "b.py": {"c.py"}, "c.py": {"d.py", "e.py"}}

    impact = compute_impact(reverse, {"a.py"}, max_hops=3)

    assert impact == {"b.py": 1, "c.py": 2, "d.py": 3, "e.py": 3}
    assert requires_verification(impact) == {"b.py"}

    limited = compute_impact(reverse, {"a.py"}, max_hops=3, limit=2)
    assert len(limited) == 2


def test_tokenize_handles_cjk_bigrams() -> None:
    assert "导出" in tokenize("加个导出按钮")
    assert "button" in tokenize("Button")


def test_bm25_prefers_relevant_document() -> None:
    index = BM25Index(
        {
            "a.py": "def export_button(): pass",
            "b.py": "def compute_total(): pass",
            "c.py": "导出按钮实现",
        }
    )

    english = index.search("export button")
    chinese = index.search("导出按钮")

    assert english[0][0] == "a.py"
    assert chinese[0][0] == "c.py"
    assert index.search("") == []


def test_rrf_fuses_rankings() -> None:
    fused = rrf([["a", "b"], ["b", "a"]])

    assert set(fused) == {"a", "b"}
    assert fused["a"] == fused["b"], "两边名次对称时得分相同"


def test_salience_prefers_src_over_tests() -> None:
    assert path_weight("src/ui/Button.tsx") > 1.0
    assert path_weight("tests/test_button.py") < 1.0
    assert path_weight("docs/guide.md") < 1.0

    ranked = rerank({"src/a.py:1": 1.0, "src/a.py:2": 1.0, "src/a.py:3": 1.0})
    assert len(ranked) == 2, "每文件最多保留两条"


def test_physarum_reinforce_decay_prune() -> None:
    grown = reinforce(1.0, flow=1.0)
    assert grown > 1.0

    assert reinforce(1.0, flow=1.0, growth=0.0, dt=300.0) < 1.0
    assert decay(1.0, dt=300.0) < 1.0
    assert prune(0.01) == 0.0
    assert prune(0.2) == 0.2
    assert reinforce(10.0, flow=5.0) <= 5.0, "权重有上限"


# ---- 阶段 8 接线：词汇重排只调序不减候选；physarum 边权持久化 ----

from devprompt_ai.domain.models import Candidate  # noqa: E402
from devprompt_ai.domain.retrieval.candidates import reorder_by_lexicon  # noqa: E402
from devprompt_ai.memory.repo_index import SQLiteRepoIndex  # noqa: E402


def _candidate(name: str, path: str, score: float = 1.0) -> Candidate:
    return Candidate(name=name, path=path, line=1, score=score, source="symbol")


def test_reorder_by_lexicon_prefers_query_match_and_impl_path() -> None:
    query = "把 Button 改成 primary-500"
    toast = _candidate("Toast", "src/ui/Toast.tsx")
    button_impl = _candidate("Button", "src/ui/Button.tsx")
    button_test = _candidate("Button", "tests/ui/button.test.tsx")

    out = reorder_by_lexicon([button_test, toast, button_impl], query)

    assert len(out) == 3, "只调序不减候选（MUST-09）"
    assert sorted((c.name, c.path) for c in out) == sorted(
        (c.name, c.path) for c in (toast, button_impl, button_test)
    ), "成员集合不变"
    assert out[0].name == "Button" and out[0].path.startswith("src/")


def test_reorder_by_lexicon_keeps_single_and_empty() -> None:
    solo = [_candidate("A", "src/a.py")]

    assert reorder_by_lexicon([], "查询") == []
    assert reorder_by_lexicon(solo, "查询") == solo


async def test_reinforce_edges_grow_bounded_and_surface_in_weights(tmp_path) -> None:
    index = SQLiteRepoIndex(str(tmp_path / "graph.db"))
    # 边方向：src/a.py 导入 src/b.py → 强化 (src=a, dst=b) 这条边
    await index.replace_file("p", "src/a.py", [], [("src/b.py", "import", "")])

    await index.reinforce_edges("p", [("src/a.py", "src/b.py")])
    first = (await index.edge_weights("p", "src/b.py"))["src/a.py"]
    assert first > 1.0, "访问一次即强化"

    for _ in range(60):
        await index.reinforce_edges("p", [("src/a.py", "src/b.py")])
    assert (await index.edge_weights("p", "src/b.py"))["src/a.py"] <= 5.0, "权重有上限"


async def test_repo_edges_migration_adds_weight_column(tmp_path) -> None:
    """旧库升级：无 weight 列的 repo_edges 由写入路径自动补列。"""
    import sqlite3

    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE repo_edges ("
            " project_root TEXT NOT NULL, src_path TEXT NOT NULL, dst_path TEXT NOT NULL,"
            " kind TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT '',"
            " PRIMARY KEY (project_root, src_path, dst_path, kind, symbol))"
        )

    index = SQLiteRepoIndex(db)
    await index.replace_file("p", "src/a.py", [], [("src/b.py", "import", "")])
    await index.reinforce_edges("p", [("src/a.py", "src/b.py")])

    assert (await index.edge_weights("p", "src/b.py"))["src/a.py"] > 1.0
