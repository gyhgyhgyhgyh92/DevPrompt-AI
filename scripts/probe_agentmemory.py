"""agentmemory 契约探测（2026-11-22）。

用途：在接入 Reflection 前，用真实侧车探明 REST 的**请求/响应字段形状**，
把结果落成 fixture 供适配器与测试使用——不靠 README 猜字段。

探测三件事：

1. ``GET /agentmemory/health`` 是否可达（鉴权是否需要）；
2. ``POST /agentmemory/remember``：``agentId`` 放 body 还是 query 才被接受；
3. ``POST /agentmemory/smart-search``：命中项的字段名（content / text / memory）。

示例：

    uv run python scripts/probe_agentmemory.py
    uv run python scripts/probe_agentmemory.py --base-url http://127.0.0.1:3111

侧车未启动或密钥缺失时打印安装提示并 exit 0（不阻塞开发与 CI）。
本脚本不进 CI，不打印密钥。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:3111"
DEFAULT_SECRET_PATH = "~/.agentmemory/secret"
DEFAULT_OUT_DIR = "tests/fixtures/agentmemory"

#: 探测专用桶与内容：不污染真实经验，便于侧车侧按 agentId 清理。
PROBE_AGENT_ID = "devprompt-probe"
PROBE_CONTENT = "devprompt probe：该仓库使用 pnpm 与 ruff"
PROBE_QUERY = "这个仓库用什么包管理器"

HEADLESS_HINT = (
    "未探测到 agentmemory 侧车（或缺少密钥）。\n"
    "  安装并启动（Node >= 20）：npx -y @agentmemory/agentmemory@latest\n"
    "  密钥默认位于 ~/.agentmemory/secret\n"
    "  脚本按契约未知处理，退出码 0，不影响后续实现。"
)


def _read_secret(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        return ""
    return file.read_text(encoding="utf-8").strip()


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


async def _probe(
    client: httpx.AsyncClient, path: str, payload: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    """发一次请求并把「请求 + 状态 + 响应」原样记录，供 fixture 使用。"""
    try:
        resp = await client.post(path, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001 - 探测脚本：任何失败都转成记录
        return {"request": payload, "error": type(exc).__name__}
    return {
        "request": payload,
        "status": resp.status_code,
        "response": _json_or_text(resp),
    }


async def _run(base_url: str, secret: str, out_dir: Path) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        try:
            health = await client.get("/agentmemory/health", headers=headers)
        except Exception as exc:  # noqa: BLE001 - 侧车未启动即走提示分支
            return {"reachable": False, "reason": type(exc).__name__}

        report: dict[str, Any] = {
            "reachable": True,
            "health": {"status": health.status_code, "response": _json_or_text(health)},
        }

        # agentId 的两种传递方式各试一次——哪种被接受由真实响应决定
        report["remember_body_agent_id"] = await _probe(
            client,
            "/agentmemory/remember",
            {"content": PROBE_CONTENT, "concepts": ["probe"], "agentId": PROBE_AGENT_ID},
            headers,
        )
        report["remember_query_agent_id"] = await _probe(
            client,
            f"/agentmemory/remember?agentId={PROBE_AGENT_ID}",
            {"content": PROBE_CONTENT, "concepts": ["probe"]},
            headers,
        )
        report["smart_search_body_agent_id"] = await _probe(
            client,
            "/agentmemory/smart-search",
            {"query": PROBE_QUERY, "limit": 3, "agentId": PROBE_AGENT_ID},
            headers,
        )
        report["smart_search_query_agent_id"] = await _probe(
            client,
            f"/agentmemory/smart-search?agentId={PROBE_AGENT_ID}",
            {"query": PROBE_QUERY, "limit": 3},
            headers,
        )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_agentmemory", description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="侧车地址")
    parser.add_argument("--secret-path", default=DEFAULT_SECRET_PATH, help="Bearer 密钥文件")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="fixture 输出目录")
    args = parser.parse_args(argv)

    secret = _read_secret(args.secret_path)
    report = asyncio.run(_run(args.base_url, secret, Path(args.out_dir)))

    if not report.get("reachable"):
        print(HEADLESS_HINT)
        print(f"  连接失败：{report.get('reason', 'unknown')}（{args.base_url}）")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    remember = {
        "probed_at": "2026-11-22",
        "agent_id": PROBE_AGENT_ID,
        "body_agent_id": report["remember_body_agent_id"],
        "query_agent_id": report["remember_query_agent_id"],
    }
    search = {
        "probed_at": "2026-11-22",
        "agent_id": PROBE_AGENT_ID,
        "body_agent_id": report["smart_search_body_agent_id"],
        "query_agent_id": report["smart_search_query_agent_id"],
    }
    (out_dir / "remember.json").write_text(
        json.dumps(remember, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "smart_search.json").write_text(
        json.dumps(search, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"health: {report['health']['status']}")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:2000])
    print(f"\nfixture 已写入 {out_dir}（其中不含密钥）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
