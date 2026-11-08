"""思考过程的动作观测层（2026-10-20）：把真实执行的 rg / 读文件上报成卡片。

## 为什么放在 harness

用户要看到「真实指令与文件」，但 domain 不得有 I/O、也不得依赖 harness 实现
（MUST-06）。故以装饰器包住 ``CommandRunner`` / ``FileReader``：``locate`` /
``facts`` 的调用语义零改动，只换传入的实例。包装器**按请求构造**，不挂单例状态。

## 脱敏（MUST-19）

卡片里只允许出现仓库相对路径：

- ``cwd`` 一律不展示（它必然是绝对路径）
- 读文件路径先去掉 ``root`` 前缀
- 残留的盘符路径收窄为末两段（``D:/a/b/c`` → ``b/c``）
- 测试专用的 ``--route-key=*`` 直接剔除

观测是旁路：``emit`` 自身失败只记 debug，绝不影响检索主链。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from typing import Final

from devprompt_ai.common.process import (
    ExecutableNotFoundError,
    ProcessError,
    ProcessTimeoutError,
)
from devprompt_ai.domain.progress import ActionInfo, ProgressEvent, ProgressSink, display_path
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader
from devprompt_ai.harness.output_store import persist, raw_path
from devprompt_ai.harness.output_summary import summarize_output, threshold_for, with_footer

logger = logging.getLogger(__name__)

_ROUTE_KEY_PREFIX: Final = "--route-key="
_MAX_DETAIL: Final = 160
#: 动作输出上限（渲染成可展开代码块；超限截断并标记）
_OUTPUT_MAX_LINES: Final = 20
_OUTPUT_MAX_CHARS: Final = 2000

#: 盘符绝对路径（D:/x/y、D:\x\y）：卡片里整体收窄为末两段。
_ABS_PATH_RE: Final = re.compile(r"[A-Za-z]:[\\/][^\s\"']*")

#: 动作标题按测试路由键推断（键随后被剔除，仅用于命名）。
_TITLES: Final[dict[str, str]] = {
    "symbol": "检索符号",
    "tokdef": "查找样式 token",
    "testid": "检查测试锚点",
    "states": "检查状态样式",
    "def": "定位符号定义",
}


def redact(text: str, root: str) -> str:
    """抹掉绝对路径前缀，只留可展示的相对形式（分隔符统一为 ``/``）。"""
    for marker in {root, root.replace("\\", "/"), root.replace("/", "\\")}:
        if marker and marker not in {".", "/", "\\"}:
            text = text.replace(marker.rstrip("/\\") + "/", "").replace(
                marker.rstrip("/\\") + "\\", ""
            )
    return _ABS_PATH_RE.sub(lambda m: display_path(m.group(0)), text).replace("\\", "/")


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…"


def _output(lines: list[str], root: str) -> str:
    """把命令输出脱敏后截断（≤20 行 / ≤2000 字符），超限追加省略标记。

    先 ``redact`` 再截断：绝对路径不能出现在前端（MUST-19）。
    """
    if not lines:
        return ""
    kept = [redact(line, root) for line in lines]
    truncated = False
    if len(kept) > _OUTPUT_MAX_LINES:
        kept = kept[:_OUTPUT_MAX_LINES]
        truncated = True
    text = "\n".join(kept)
    if len(text) > _OUTPUT_MAX_CHARS - 8:
        text = text[: _OUTPUT_MAX_CHARS - 8]
        truncated = True
    return text + ("\n…（已截断）" if truncated else "")


def _title(args: list[str]) -> str:
    for arg in args:
        if not arg.startswith(_ROUTE_KEY_PREFIX):
            continue
        kind = arg[len(_ROUTE_KEY_PREFIX) :].split(":", 1)[0]
        if kind in _TITLES:
            return _TITLES[kind]
    return "检索代码"


def _tool_of(args: list[str]) -> str:
    """按可执行名映射语义密度档位（output_summary 阈值系数用）。"""
    name = (args[0] if args else "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return {"rg": "grep", "ctags": "repo_map"}.get(name, name or "bash")


def _clip_card(text: str) -> str:
    """行数已由摘要控制，这里只兜底字符上限（MUST-19 ≤2000 字符）。"""
    if len(text) <= _OUTPUT_MAX_CHARS:
        return text
    return text[:_OUTPUT_MAX_CHARS] + "\n…（已截断）"


async def _governed_output(
    text: str, *, tool: str, success: bool, root: str, governance: bool = True
) -> str:
    """C1–C5：超阈值的输出先落盘全量，卡片只给摘要 + 回读指针。

    摘要行数按 MUST-19 的 20 行上限反推（footer 占 1 行），截断对用户可见且
    明确提示「不要重跑命令」；落盘内容先脱敏——回读 API 会原样发给前端。
    `tool_output_governance` 关闭时走改造前的截断口径（灰度闸口）。
    """
    if not governance or len(text) <= threshold_for(tool):
        return _output(text.splitlines(), root)
    call_id = f"{tool}:{hashlib.sha256(text.encode('utf-8', 'ignore')).hexdigest()}"
    saved = await persist(call_id, redact(text, root))
    summary = summarize_output(
        "\n".join(redact(line, root) for line in text.splitlines()),
        success=success,
        success_lines=_OUTPUT_MAX_LINES - 2,
        failure_budget=_OUTPUT_MAX_LINES - 11,
    )
    # persist 失败返回空串：footer 退化为「不要重跑」提示，不给死指针
    ref = f"/api/v1/artifacts/{raw_path(call_id).stem}" if saved else ""
    return _clip_card(with_footer(summary, ref))


class TracingRunner:
    """转发真实命令，并对每次调用上报一张动作卡片。"""

    def __init__(
        self,
        inner: CommandRunner,
        sink: ProgressSink,
        root: str,
        phase: Callable[[], str] | None = None,
        governance: bool = True,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._root = root
        self._phase = phase or (lambda: "")
        self._governance = governance

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        # 只改展示副本，args 本身绝不能动（否则改变真实 rg 行为）
        shown = [arg for arg in args if not arg.startswith(_ROUTE_KEY_PREFIX)]
        started = time.monotonic()
        try:
            out = await self._inner.run(
                args, timeout=timeout, allowed_exit_codes=allowed_exit_codes, cwd=cwd
            )
        except (ExecutableNotFoundError, ProcessTimeoutError):
            # 工具没装 / 命令超时不是「这条命令没匹配到」：降级会让用户只拿到保守方案
            # 却永远查不到真因，故原样抛出（2026-11-04 用户裁定降级范围的边界）。
            raise
        except ProcessError as exc:
            # 非允许退出码（rg 未命中即 exit 1）→ 降级：先上报失败卡片，再返回空串，
            # 调用方按「无匹配」处理，整轮流程不再因一次检索失败而中断（MUST-19：stderr 先脱敏）。
            await self._emit(
                ActionInfo(
                    title=_title(args),
                    detail=_clip(redact(" ".join(shown), self._root)),
                    scope=f"Exit code {exc.code}",
                    output=_output((exc.stderr or str(exc)).splitlines(), self._root),
                    status="failed",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
            return ""
        lines = out.splitlines()
        hits = sum(1 for line in lines if line.strip())
        await self._emit(
            ActionInfo(
                title=_title(args),
                detail=_clip(redact(" ".join(shown), self._root)),
                scope=f"命中 {hits} 行" if hits else "无匹配",
                output=await _governed_output(
                    out,
                    tool=_tool_of(args),
                    success=True,
                    root=self._root,
                    governance=self._governance,
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        )
        return out

    async def _emit(self, action: ActionInfo) -> None:
        try:
            await self._sink.emit(ProgressEvent(action=action, phase=self._phase()))
        except Exception:  # noqa: BLE001 - 观测是旁路，失败不得打断检索
            logger.debug("trace.emit_failed", exc_info=True)


class TracingReader:
    """转发文件读取，并对每次读取上报一张动作卡片（存在性检查不上报）。"""

    def __init__(
        self,
        inner: FileReader,
        sink: ProgressSink,
        root: str,
        phase: Callable[[], str] | None = None,
        governance: bool = True,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._root = root
        self._phase = phase or (lambda: "")
        self._governance = governance

    async def read(self, path: str) -> str:
        started = time.monotonic()
        text = await self._inner.read(path)
        lines = text.splitlines()
        try:
            await self._sink.emit(
                ProgressEvent(
                    phase=self._phase(),
                    action=ActionInfo(
                        title="读取文件",
                        detail=_clip(redact(path, self._root)),
                        scope=f"L1-{len(lines)}" if lines else "",
                        output=await _governed_output(
                            text,
                            tool="read_file",
                            success=True,
                            root=self._root,
                            governance=self._governance,
                        ),
                        duration_ms=int((time.monotonic() - started) * 1000),
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - 同上
            logger.debug("trace.emit_failed", exc_info=True)
        return text

    async def exists(self, path: str) -> bool:
        # 一次取证会做 5 次存在性检查，逐条上报只会刷出噪音卡片
        return await self._inner.exists(path)
