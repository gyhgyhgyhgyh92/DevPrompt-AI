"""敏感值脱敏工具（MUST-19：密钥恒脱敏回显，明文不落界面/日志/响应）。"""

from __future__ import annotations


def mask_secret(value: str) -> str:
    """API Key 脱敏展示：保留首 3 位与末 4 位，中间恒为掩码（短值整体掩码）。"""
    if not value:
        return ""
    if len(value) < 10:
        return "••••"
    return f"{value[:3]}••••{value[-4:]}"
