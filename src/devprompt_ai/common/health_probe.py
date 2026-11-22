"""本地伴生服务的健康探测（2026-11-22）：给 ``GET /health`` 用的通用能力。

为什么放在 ``common`` 而不是 ``harness``：``interfaces/api`` 禁止 import ``harness``
（Web 薄壳约束，MUST-06），而健康检查必须能从 api 层直接探测外部服务。
本模块只做「读密钥 → GET 一次 → 回 (ok, 短原因)」，不含任何业务判定。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx


def _read_secret_text(secret_path: str) -> str:
    """同步读密钥文件；缺失/不可读一律返回空串（调用方按「未配置」处理）。"""
    try:
        return Path(secret_path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


async def probe_service(
    base_url: str, secret_path: str, health_path: str, timeout: float = 1.5
) -> tuple[bool, str]:
    """探测需要 Bearer 鉴权的本地服务；只回 (ok, 短原因)，不抛异常、不写事件。

    密钥读取是阻塞 I/O，按 MUST-13 卸载到线程；失败原因只用稳定标记
    （``secret_missing`` / ``http_401`` / 异常类型名），文案由调用方决定。
    """
    secret = await asyncio.to_thread(_read_secret_text, secret_path)
    if secret == "":
        return False, "secret_missing"
    root = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=root, timeout=timeout) as client:
            resp = await client.get(health_path, headers={"Authorization": f"Bearer {secret}"})
    except Exception as exc:  # noqa: BLE001 - 探测失败只报类型，不抛
        return False, type(exc).__name__
    if resp.status_code != 200:
        return False, f"http_{resp.status_code}"
    return True, root
