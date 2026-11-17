"""三轮递进式关联测试：同一进程、同一会话、仅原句变化。

设计要点（详见 .trae/documents/三轮递进式关联测试方案.md）：

* 进程内调用 ``build_default`` + ``optimize``，不起 uvicorn —— 消除端口、进程存活、
  SSE 帧解析三类外部变量，天然保证单实例 / 单 DB / 单配置。
* 三轮共用同一 ``session_id``，唯一变化量是 ``sentence``。
* 每轮前后采集环境指纹（.env / settings.json / 配置摘要 / 项目路径 / 会话 / PID），
  任一变化即判定该轮 INVALID 并中止。
* 三项指标全部确定性计算，不依赖主观判断。

运行：``uv run python eval/multiturn/run_3rounds.py``
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from devprompt_ai.common.i18n import Locale
from devprompt_ai.config import AppConfig
from devprompt_ai.service import FlowSnapshot, ForgeService, build_default

USER_ID = "local"
PROJECT = r"D:\前端作业\实验二"
TARGET_PATH = "task/task-front/src/pages/bookManage/BookListPage.tsx"
LOCALE: Locale = "zh-CN"

#: 本次重测的唯一模型（业主指定）：关闭多模型路由，使决策 / 排序 / 生成全部走该模型，
#: 避免路由到余额不足的其它模型条目。这是相对前几次尝试的**唯一**配置差异。
FORCE_MODEL = "deepseek-flash"

ROUNDS: list[tuple[str, str]] = [
    ("R1", "将当前项目中的前端页面中的管理员界面中的新增图书按钮改为红色。"),
    (
        "R2",
        "在上一轮的基础上，把这个按钮的红色改成橙色（warning），"
        "保留原有图标和尺寸，不要改动点击逻辑。",
    ),
    (
        "R3",
        "沿用上一轮确定的这套配色与写法，同样应用到本页面的\u201c编辑\u201d按钮上，"
        "保持两处视觉一致。",
    ),
]

#: 四段式小标题（A5 判定）
_SECTION_MARKS = ("## 一、", "## 二、", "## 三、", "## 四、")

#: 锚点抽取：反引号片段 / JSX 组件 / path:line / 属性赋值
_ANCHOR_RE = re.compile(
    r"`([^`\n]{2,120})`"
    r"|<([A-Z][\w.]*)"
    r"|\b([\w./-]+\.(?:tsx?|jsx?|css|less|scss|vue):\d+)"
    r"|(\w+=\"[^\"\n]{0,60}\")"
)

#: 逐轮 A3 期望：(定位关键词任一命中, 变更关键词任一命中)，两组都满足才算通过
#: 2026-11-11 修正：首组此前误写成「全部命中」，导致 R3 因正文用文案「编辑」而非
#: 标识符 `openEdit` 被判 FAIL——那比本轮任务要求更严，属于判据错误而非产出缺陷。
_A3_EXPECT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "R1": (("primary",), ("danger",)),
    "R2": (("danger",), ("warning", "colorWarning")),
    "R3": (("openEdit", "编辑"), ("warning", "colorWarning")),
}


def _sha256(path: Path) -> str:
    """文件内容摘要；缺失返回 ``<missing>``（不抛错，便于比对时区分）。"""
    if not path.exists():
        return "<missing>"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _config_digest(cfg: AppConfig) -> str:
    """配置摘要：含 api_key 的哈希（只比变化，不落明文）。"""
    parts = [
        str(cfg.llm_provider),
        str(cfg.llm_model),
        str(cfg.api_mode),
        str(cfg.multi_model_routing),
        str(cfg.db_path),
        hashlib.sha256(str(cfg.llm_api_key).encode()).hexdigest()[:16],
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _fingerprint(cfg: AppConfig, session_id: str | None) -> dict[str, str]:
    """环境指纹：六分量逐字节比对（M4）。"""
    root = Path(__file__).resolve().parents[2]
    return {
        "env_file": _sha256(root / ".env"),
        "settings": _sha256(Path.home() / ".devprompt-ai" / "settings.json"),
        "config": _config_digest(cfg),
        "project": PROJECT,
        "session": session_id or "<new>",
        "pid": str(os.getpid()),
    }


def _anchors(text: str) -> set[str]:
    """从方案正文抽取可复核锚点（路径 / 组件 / 行号 / 属性赋值）。"""
    found: set[str] = set()
    for match in _ANCHOR_RE.finditer(text):
        token = next((g for g in match.groups() if g), "")
        token = token.strip()
        if token:
            found.add(token)
    return found


#: 逐轮 A2 期望：(全部命中, 任一命中)。首版恒要求 `PageContainer`+`extra`，
#: 但 R3 改的是表格行内的「编辑」按钮，本就不在 `extra` 里——那是判据错误，
#: 不是产出缺陷（2026-11-12 修正）。
_A2_EXPECT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "R1": (("PageContainer", "extra"), ()),
    "R2": (("PageContainer", "extra"), ()),
    "R3": (("编辑",), ("操作列", "columns", "Table", "表格", "openEdit")),
}


def _score_accuracy(tag: str, snap: FlowSnapshot, variant: Any | None) -> dict[str, Any]:
    """M1：五项规则清单，等权 0/1。"""
    body = variant.body if variant is not None else ""
    blob = body + "\n" + "\n".join(variant.changes if variant is not None else [])
    must, anyof = _A3_EXPECT[tag]
    a2_all, a2_any = _A2_EXPECT[tag]
    checks = {
        "A1 定位文件正确": bool(snap.target and snap.target.path == TARGET_PATH),
        "A2 组件与属性正确": (
            all(word in body for word in a2_all)
            and (not a2_any or any(word in body for word in a2_any))
        ),
        "A3 变更代码正确": (
            any(word in blob for word in must) and any(word in blob for word in anyof)
        ),
        "A4 令牌引用正确": ("antdTheme" in blob or "#ff4d4f" in blob or "#faad14" in blob),
        "A5 四段式完整": all(mark in body for mark in _SECTION_MARKS),
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {"checks": checks, "passed": passed, "total": 5, "rate": passed / 5}


def _score_context(
    prev_snap: FlowSnapshot | None,
    prev_variant: Any | None,
    snap: FlowSnapshot,
    variant: Any | None,
    turns_ok: bool,
) -> dict[str, Any] | None:
    """M3：上下文关联匹配度；首轮无前序，返回 None。"""
    if prev_snap is None:
        return None
    c1 = int(bool(prev_snap.target and snap.target and prev_snap.target.path == snap.target.path))
    cur = _anchors(variant.body) if variant is not None else set()
    old = _anchors(prev_variant.body) if prev_variant is not None else set()
    c2 = (len(cur & old) / len(cur)) if cur else 0.0
    c3 = int(turns_ok)
    return {
        "C1 目标一致": c1,
        "C2 锚点复用率": round(c2, 3),
        "C3 历史未丢": c3,
        "rate": round((c1 + c2 + c3) / 3, 3),
    }


async def _turn_ids(svc: ForgeService, session_id: str) -> set[str]:
    """当前会话已落库的轮次 id 集合（用于 C3）。"""
    try:
        page = await svc.list_turns(USER_ID, session_id)
    except Exception:  # noqa: BLE001 - 度量辅助项，失败按「未取到」处理
        return set()
    items = getattr(page, "items", None)
    if items is None:
        items = page if isinstance(page, list) else []
    ids: set[str] = set()
    for item in items:
        turn_id = getattr(item, "turn_id", None) or (
            item.get("turn_id") if isinstance(item, dict) else None
        )
        if turn_id:
            ids.add(str(turn_id))
    return ids


async def _run_round(
    svc: ForgeService, tag: str, sentence: str, session_id: str | None
) -> tuple[FlowSnapshot, list[str]]:
    """执行一轮：optimize → 必要时自动答反问 / 确认护栏。返回最终快照与分支标记。"""
    marks: list[str] = []
    snap = await svc.optimize(
        USER_ID,
        PROJECT,
        sentence,
        request_id=f"{tag}-{uuid4().hex[:8]}",
        session_id=session_id,
        locale=LOCALE,
    )
    sid = snap.session_id
    # 反问：用 best_guess 自动作答（最多 3 轮，避免死循环）
    for _ in range(3):
        if snap.status != "ask":
            break
        answers = {item.key: (item.best_guess or "按你的建议") for item in snap.questions}
        marks.append("ask→auto-answer")
        snap = await svc.ask_followup(
            USER_ID, sid, answers, request_id=f"{tag}-ans-{uuid4().hex[:8]}"
        )
    # 护栏：一律选择继续
    if snap.status == "guardrail":
        marks.append("guardrail→continue")
        snap = await svc.guardrail_confirm(
            USER_ID, sid, True, request_id=f"{tag}-guard-{uuid4().hex[:8]}"
        )
    return snap, marks


def _snapshot_brief(snap: FlowSnapshot) -> dict[str, Any]:
    """落盘用的快照摘要（只要可复核字段，避免整份对象序列化）。"""
    return {
        "session_id": snap.session_id,
        "status": snap.status,
        "state": snap.state,
        "current_turn_id": snap.current_turn_id,
        "target": (
            {"name": snap.target.name, "path": snap.target.path, "line": snap.target.line}
            if snap.target
            else None
        ),
        "variant": (
            {
                "title": snap.variant.title,
                "body": snap.variant.body,
                "changes": snap.variant.changes,
                "claims": [claim.model_dump() for claim in snap.variant.claims],
                "fallback": snap.variant.fallback,
            }
            if snap.variant
            else None
        ),
        "facts": [{"key": f.key, "passed": f.passed} for f in snap.facts],
        "cost": (
            {"total_tokens": snap.cost.total_tokens, "llm_source": snap.cost.llm_source}
            if snap.cost
            else None
        ),
        "delivery_gate": (
            {
                "status": snap.delivery_gate.status,
                "tone": snap.delivery_gate.tone,
                "disclosure": snap.delivery_gate.disclosure,
            }
            if snap.delivery_gate
            else None
        ),
        "agent_elapsed_ms": snap.agent_elapsed_ms,
        "message": snap.message,
    }


def _print_round(
    tag: str,
    sentence: str,
    elapsed_s: float,
    snap: FlowSnapshot,
    accuracy: dict[str, Any],
    context: dict[str, Any] | None,
    marks: list[str],
) -> None:
    """轮次完成后**立即**输出三项指标（需求 4）。"""
    print("\n" + "=" * 72)
    print(f"{tag} · 原句：{sentence}")
    print("-" * 72)
    print(
        f"  状态        : {snap.status} / {snap.state}"
        + (f"  [{' , '.join(marks)}]" if marks else "")
    )
    if snap.target:
        print(f"  目标        : {snap.target.name}@{snap.target.path}:{snap.target.line}")
    if snap.delivery_gate:
        print(f"  交付门      : {snap.delivery_gate.status}（tone={snap.delivery_gate.tone}）")
    print(f"  方案标题    : {snap.variant.title if snap.variant else None}")
    print(f"  fallback    : {snap.variant.fallback if snap.variant else None}")
    print("  --- 指标 ---")
    print(
        f"  M1 准确率   : {accuracy['passed']}/{accuracy['total']} = {accuracy['rate'] * 100:.0f}%"
    )
    for name, ok in accuracy["checks"].items():
        print(f"      {'PASS' if ok else 'FAIL'}  {name}")
    print(
        f"  M2 耗时     : {elapsed_s:.2f}s"
        f"（agent_elapsed={snap.agent_elapsed_ms}ms,"
        f" tokens={snap.cost.total_tokens if snap.cost else 'N/A'}）"
    )
    if context is None:
        print("  M3 关联度   : N/A（首轮无前序上下文）")
    else:
        print(
            f"  M3 关联度   : {context['rate'] * 100:.0f}%"
            f"（C1={context['C1 目标一致']},"
            f" C2={context['C2 锚点复用率']},"
            f" C3={context['C3 历史未丢']}）"
        )


async def main() -> int:
    cfg = AppConfig()
    # 单模型模式：关闭路由后 `_model_chain` 返回 [cfg]，即 FORCE_MODEL 独占整条链
    cfg.multi_model_routing = False
    cfg.llm_model = FORCE_MODEL
    cfg.validate()
    if cfg.llm_model != FORCE_MODEL or cfg.multi_model_routing:
        print(f"模型锁定失败：llm_model={cfg.llm_model} routing={cfg.multi_model_routing}")
        return 2
    svc = await build_default(cfg)

    print(f"模型锁定：{cfg.llm_model} @ {cfg.llm_base_url}（multi_model_routing=off）")
    print("环境基线指纹：", json.dumps(_fingerprint(cfg, None), ensure_ascii=False))
    baseline = _fingerprint(cfg, None)
    session_id: str | None = None
    records: list[dict[str, Any]] = []
    prev_snap: FlowSnapshot | None = None
    prev_variant: Any | None = None

    for tag, sentence in ROUNDS:
        fp = _fingerprint(cfg, session_id)
        drift = {
            k: (baseline[k], fp[k])
            for k in ("env_file", "settings", "config", "project", "pid")
            if baseline[k] != fp[k]
        }
        if drift:
            print(f"\n[{tag}] 环境指纹变化，测试作废：{drift}")
            return 3

        start = time.perf_counter()
        try:
            snap, marks = await _run_round(svc, tag, sentence, session_id)
        except Exception as exc:  # noqa: BLE001 - 失败必须显式报告，不得伪造数据
            print(f"\n[{tag}] 执行失败：{type(exc).__name__}: {exc}")
            records.append({"round": tag, "error": f"{type(exc).__name__}: {exc}"})
            break
        elapsed = time.perf_counter() - start

        if session_id is None:
            session_id = snap.session_id
        elif snap.session_id != session_id:
            print(f"\n[{tag}] 会话被重置：{session_id} -> {snap.session_id}，测试作废")
            return 4

        variant = snap.variant
        accuracy = _score_accuracy(tag, snap, variant)
        ids = await _turn_ids(svc, session_id)
        turns_ok = bool(
            prev_snap and prev_snap.current_turn_id and prev_snap.current_turn_id in ids
        )
        context = _score_context(prev_snap, prev_variant, snap, variant, turns_ok)

        _print_round(tag, sentence, elapsed, snap, accuracy, context, marks)
        records.append(
            {
                "round": tag,
                "sentence": sentence,
                "elapsed_s": round(elapsed, 3),
                "marks": marks,
                "accuracy": accuracy,
                "context": context,
                "snapshot": _snapshot_brief(snap),
            }
        )

        if snap.status == "aborted":
            print(f"\n[{tag}] status=aborted，停止后续轮次")
            break
        prev_snap, prev_variant = snap, variant

    out = Path(__file__).with_name("result-2026-11-11.json")
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始结果已落盘：{out}")

    print("\n" + "=" * 72)
    print("汇总")
    print(f"{'轮次':<4}{'准确率':<10}{'耗时(s)':<10}{'关联度':<10}{'fallback':<10}{'状态'}")
    for rec in records:
        if "error" in rec:
            print(f"{rec['round']:<4}{'—':<10}{'—':<10}{'—':<10}{'—':<10}ERROR")
            continue
        ctx = rec["context"]
        ctx_text = "N/A" if ctx is None else f"{ctx['rate'] * 100:.0f}%"
        variant = rec["snapshot"]["variant"]
        fallback = "—" if variant is None else str(variant["fallback"])
        print(
            f"{rec['round']:<4}"
            f"{rec['accuracy']['rate'] * 100:>6.0f}%   "
            f"{rec['elapsed_s']:>7.2f}   "
            f"{ctx_text:>6}    "
            f"{fallback:<10}"
            f"{rec['snapshot']['status']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
