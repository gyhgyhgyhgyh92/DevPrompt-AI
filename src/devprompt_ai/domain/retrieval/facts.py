"""F-104 事实取证：ripgrep 逐项验证 7 项客观事实，布尔 + 证据，无「未知」。

证据截断 200 字符（MUST-09 精神：控制进入 state 的体积）。
I/O 全部经 CommandRunner / FileReader Protocol（MUST-06）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from devprompt_ai.domain.models import CodeLocation, FactResult
from devprompt_ai.domain.retrieval.paths import safe_join
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader

_RG_ALLOWED = frozenset({0, 1})
_EVIDENCE_LIMIT = 200

_KNOWN_EXTS = {".tsx", ".ts", ".jsx", ".js", ".vue", ".py", ".css", ".scss", ".less", ".html"}

#: 前端/样式后缀：只有这类目标文件才可能同时具备 token / testid / 状态样式
_FRONTEND_EXTS = frozenset({".tsx", ".jsx", ".vue", ".css", ".scss", ".less"})
#: 仅对前端/样式有意义的三个事实。后端项目里它们恒 False，
#: 会把 `facts_complete` 永久钉在 False、C 档永远不可达（2026-11-05 修正）。
_FRONTEND_ONLY = frozenset({"token_defined", "has_data_testid", "has_state_styles"})

#: 已知 UI 组件库的导入特征。这些库的 hover/focus/active 样式定义在库内部，
#: 业务文件必然零命中；据此判 has_state_styles「不适用」而不是「未通过」。
_UI_LIB_SIGNALS: dict[str, tuple[str, ...]] = {
    "antd": ("from 'antd'", 'from "antd"'),
    "mui": ("@mui/material", "@mui/system"),
    "element-plus": ("element-plus",),
    "naive-ui": ("naive-ui",),
    "chakra": ("@chakra-ui",),
}


def _ui_lib_of(text: str) -> str:
    """返回目标文件导入的已知 UI 组件库名；未命中返回空串。"""
    for lib, signals in _UI_LIB_SIGNALS.items():
        if any(signal in text for signal in signals):
            return lib
    return ""


def _ext_of(path: str) -> str:
    last_seg = path.rsplit("/", 1)[-1]
    return ("." + last_seg.rsplit(".", 1)[-1]) if "." in last_seg else ""


def is_applicable(key: str, ext: str) -> bool:
    """该事实在该目标文件类型下是否有意义。"""
    return ext in _FRONTEND_EXTS or key not in _FRONTEND_ONLY


def is_evidence_complete(facts: Sequence[FactResult]) -> bool:
    """适用项全部通过才算取证完备（取代「七项全过」）。

    空集合返回 False：没有事实就没有证据，不能算完备。
    """
    applicable = [fact for fact in facts if fact.applicable]
    return bool(applicable) and all(fact.passed for fact in applicable)


def is_probe_complete(
    *,
    evidence_ok: bool,
    measured: bool,
    confidence: float | None,
    threshold: float,
    has_unknowns: bool,
    judged: bool,
) -> bool:
    """研判结果是否足以升到最高档（2026-11-07 修复静默降质）。

    ``judged`` 必须为真：模型参数畸形时 fallback 返回空 ``judgments``，
    旧口径把「没有未知」当成「信息足够」，档位会虚高到最高档。
    """
    if not evidence_ok or has_unknowns:
        return False
    if measured:
        return confidence is not None and confidence >= threshold
    return judged


def _ev(raw: str) -> str:
    raw = raw.strip().replace("\n", " ⏎ ")
    return raw[:_EVIDENCE_LIMIT] if raw else "未找到"


def _rg_cwd(root: str) -> str | None:
    """rg 必须从**项目根**起搜。

    进程 cwd 是本工具自身仓库，而 `--glob` 用的是目标项目的相对路径——不传 cwd 时
    永远匹配不到，七项取证会集体误判为「未找到」（真实用户实测的 5 项反问即由此而来）。
    """
    return None if root in (".", "") else root


async def verify_facts(
    location: CodeLocation,
    sentence: str,
    runner: CommandRunner,
    reader: FileReader,
    *,
    root: str = ".",
) -> list[FactResult]:
    """逐项验证七项事实（F-104 行为列）；每项独立验证，互不短路。

    root：目标项目根（FileReader 文件系统访问需拼绝对路径，rg 相对搜索不受影响）。
    """

    def _fs(rel: str) -> str:
        # MUST-20：越界或非法路径返回空串，等价于「文件不存在」。
        return safe_join(root, rel)

    path, name = location.path, location.symbol_name
    ext = _ext_of(path)

    def applicable(key: str) -> bool:
        return is_applicable(key, ext)

    token = location.tokens[0] if location.tokens else ""

    async def _token_search() -> str:
        if not token:
            return ""
        # token 形如 --color-primary-500，直接当位置参数会被 rg 当成命令行选项
        # （实测 rg: unrecognized flag），必须用 -e 显式声明「这是模式」
        return await runner.run(
            [
                "rg",
                "--fixed-strings",
                "-n",
                "-e",
                token,
                "--glob",
                "*.css",
                ".",
                f"--route-key=tokdef:{token}",
            ],
            allowed_exit_codes=_RG_ALLOWED,
            cwd=_rg_cwd(root),
        )

    async def _first_test_path() -> str:
        """F-103 已定位的 test_paths 逐一存在性检查，命中即返回。"""
        for tp in location.test_paths:
            if await reader.exists(_fs(tp)):
                return tp
        return ""

    async def _read_target() -> str:
        """读目标文件文本，用于识别「状态样式由组件库提供」的项目。

        MUST-20：越界路径返回空串，不读文件；读取失败按无文本处理。
        """
        full = _fs(path)
        if not full:
            return ""
        try:
            return await reader.read(full)
        except Exception:  # noqa: BLE001 - 读取失败不阻断其它取证项
            return ""

    # 互不依赖的只读取证并发启动；结果按固定顺序组装，FactResult 顺序不变。
    # 目标文件文本单独起任务再 await：asyncio.gather 的类型重载最多覆盖 6 个参数，
    # 直接拼成 7 元组会让 mypy 退化为 object。
    target_task = asyncio.ensure_future(_read_target())
    exists, sym_out, tok_out, tid_out, states_out, test_path = await asyncio.gather(
        reader.exists(_fs(path)),
        runner.run(
            [
                "rg",
                "--fixed-strings",
                "-n",
                name,
                "--glob",
                path,
                ".",
                f"--route-key=symbol:{path}",
            ],
            allowed_exit_codes=_RG_ALLOWED,
            cwd=_rg_cwd(root),
        ),
        _token_search(),
        runner.run(
            ["rg", "-n", "data-testid", "--glob", path, ".", f"--route-key=testid:{path}"],
            allowed_exit_codes=_RG_ALLOWED,
            cwd=_rg_cwd(root),
        ),
        runner.run(
            [
                "rg",
                "-n",
                "-e",
                ":hover",
                "-e",
                ":focus",
                "-e",
                ":active",
                "--glob",
                path,
                ".",
                f"--route-key=states:{path}",
            ],
            allowed_exit_codes=_RG_ALLOWED,
            cwd=_rg_cwd(root),
        ),
        _first_test_path(),
    )
    target_text = await target_task

    sym_hit = next((line for line in sym_out.splitlines() if name in line), "")
    tok_hit = next((line for line in tok_out.splitlines() if token and token in line), "")
    if not tok_hit and location.token_hits:
        # 2026-11-12：目标文件没有 CSS 自定义属性时，回退到 JS 主题对象证据。
        # Ant Design 这类项目用 `colorError: '#ff4d4f'` 定义色板，`--xxx` 恒为零命中，
        # 旧实现会把 token_defined 永久钉在 False（实测实验二项目 3/7 通过即由此而来）。
        # 主题命中由 locate 阶段的同一次 rg 探得，这里复用，零额外 I/O。
        tok_hit = f"theme: {location.token_hits[0]}"
    tid = next((line for line in tid_out.splitlines() if "data-testid" in line), "")
    st = next(
        (
            line
            for line in states_out.splitlines()
            if any(marker in line for marker in (":hover", ":focus", ":active"))
        ),
        "",
    )
    # 2026-11-12：状态样式零命中且目标文件从已知组件库导入 → 判「不适用」。
    # AntD/MUI 等库的 hover 定义在库内部，业务文件恒零命中；判「通过」等于伪造证据，
    # 判「未通过」则会让这类项目的适用项永远差一项。省下的证据里如实记库名。
    states_lib = "" if st else _ui_lib_of(target_text)

    return [
        FactResult(
            "target_file_exists",
            exists,
            f"file={path}" if exists else f"missing={path}",
            applicable("target_file_exists"),
        ),
        FactResult(
            "symbol_in_file",
            bool(sym_hit),
            _ev(sym_hit),
            applicable("symbol_in_file"),
        ),
        FactResult(
            "token_defined",
            bool(tok_hit),
            _ev(tok_hit),
            applicable("token_defined"),
        ),
        FactResult(
            "has_data_testid",
            bool(tid),
            _ev(tid),
            applicable("has_data_testid"),
        ),
        FactResult(
            "has_state_styles",
            bool(st),
            f"ui_lib={states_lib}" if states_lib else _ev(st),
            applicable("has_state_styles") and not states_lib,
        ),
        FactResult(
            "file_type_matches",
            ext in _KNOWN_EXTS,
            f"ext={ext or 'none'}",
            applicable("file_type_matches"),
        ),
        FactResult(
            "test_file_exists",
            bool(test_path),
            f"test={test_path}" if test_path else "未找到",
            applicable("test_file_exists"),
        ),
    ]
