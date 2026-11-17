"""JSON 主体提取（2026-11-07 清理 shortcut）：括号配平取代首尾截取。

覆盖真实模型输出的四种常见脏形态：前后说明、围栏、正文里带花括号、字符串里带转义引号。
"""

from __future__ import annotations

import json

from devprompt_ai.harness.llm import _extract_json


def test_plain_object() -> None:
    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_surrounding_prose_is_dropped() -> None:
    text = '好的，结果如下：\n{"a": 1}\n以上是结果，如有疑问请告诉我。'
    assert json.loads(_extract_json(text)) == {"a": 1}


def test_fenced_block() -> None:
    text = '```json\n{"a": {"b": 2}}\n```'
    assert json.loads(_extract_json(text)) == {"a": {"b": 2}}


def test_fenced_block_with_trailing_prose() -> None:
    text = '```json\n{"a": 1}\n```\n（说明：字段含义见文档）'
    assert json.loads(_extract_json(text)) == {"a": 1}


def test_braces_inside_string() -> None:
    text = '{"prompt": "if (x) { return {a: 1} }", "n": 2}'
    assert json.loads(_extract_json(text)) == {"prompt": "if (x) { return {a: 1} }", "n": 2}


def test_escaped_quotes_inside_string() -> None:
    text = '{"s": "say \\"}\\" now", "n": 1}'
    assert json.loads(_extract_json(text)) == {"s": 'say "}" now', "n": 1}


def test_trailing_braces_after_object_are_ignored() -> None:
    """旧实现用 rfind('}') 会把说明里的 `{...}` 吞进来，配平后只取第一个完整对象。"""
    text = '{"a": 1}\n备注：字段顺序见 {schema} 文件'
    assert json.loads(_extract_json(text)) == {"a": 1}


def test_unbalanced_output_falls_back_to_raw() -> None:
    text = '{"a": 1'  # 截断输出：配平失败时原样返回，让上层按解析失败处理
    assert _extract_json(text) == '{"a": 1'


def test_no_object_returns_text() -> None:
    assert _extract_json("不是 JSON") == "不是 JSON"
