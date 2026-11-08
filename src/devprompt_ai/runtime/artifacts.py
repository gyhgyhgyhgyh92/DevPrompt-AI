"""工件回读（C3）：被截断的工具全量输出。

interfaces 不得直连存储（MUST-06），故取数封装在本层；id 只接受
`output_store.raw_path` 产出的 sha256 十六进制摘要，杜绝路径拼接。
"""

from __future__ import annotations

from devprompt_ai.harness.output_store import read_by_id

_ID_CHARS = frozenset("0123456789abcdef")


async def read_tool_artifact(artifact_id: str) -> str | None:
    """按 id 取回全量输出；id 非法或文件已过期（1 小时清理）返回 None。"""
    if len(artifact_id) != 24 or not set(artifact_id.lower()) <= _ID_CHARS:
        return None
    return await read_by_id(artifact_id)
