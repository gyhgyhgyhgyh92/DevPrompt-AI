"""F-103 全文定位：rg 定位定义行号，文件内容提取选择器与设计 token，命名约定找测试。

I/O 全部经 CommandRunner / FileReader Protocol（MUST-06）。
测试路由键约定：rg 参数中的 --route-key=<键> 仅被测试 Fake 识别，
LocalCommandRunner 在转发真实进程前会过滤掉它（见 common/process.py 的 run_command）。

2026-11-11 增补：带行号的目标代码片段 + 项目设计令牌证据。四段式方案要写出
「位于某组件某属性内」与「原代码 → 新代码」，仅靠七项布尔做不到；片段只走生成层，
不进 facts_summary（MUST-09 约束的是决策层 state 体积）。
"""

from __future__ import annotations

import json
import re

from devprompt_ai.common.text import tokenize_sentence
from devprompt_ai.domain.models import CodeLocation, Symbol
from devprompt_ai.domain.retrieval.candidates import expand_zh_en
from devprompt_ai.domain.retrieval.paths import safe_join
from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader

_RG_ALLOWED = frozenset({0, 1})  # 1 = 无匹配（rg 语义，正常）

_CLASS_RE = re.compile(r"""(?:className|class)\s*=\s*["'{]([^"'}]+)["'}]""")
_TOKEN_RE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*")

#: 片段窗口：锚点前 15 行（够看到外层组件与属性）后 20 行（够看到相邻 JSX）。
_EXCERPT_BEFORE = 15
_EXCERPT_AFTER = 20
#: 片段总字符上限（约 1k token）。超限截断并标注，不静默丢弃。
_EXCERPT_MAX_CHARS = 2400
#: 锚点判据：一行至少命中这么多个原句词元才算「相关行」，避免零散单词误锚。
_ANCHOR_MIN_HITS = 2
#: 锚点窗口：本行 + 后 N 行一起算命中。JSX 常写成多行
#: （`<Button ...>` 与文案「编辑」分处两行），只按单行打分会把命中拆散、双双不达阈值。
_ANCHOR_WINDOW = 2
#: 不具识别性的词元：元素类型、属性/样式、动作与指代词。
#: 只命中这些词说明「说的是哪个元素」仍未确定（如「这个按钮的红色改成橙色」只命中
#: button/click/size），此时应结合上一轮上下文定位，不能凭它们锁定某一处。
_GENERIC_ANCHOR_TERMS = frozenset(
    {
        "按钮",
        "button",
        "输入框",
        "input",
        "表单",
        "form",
        "表格",
        "table",
        "弹窗",
        "modal",
        "dialog",
        "下拉",
        "dropdown",
        "combobox",
        "页面",
        "page",
        "组件",
        "component",
        "尺寸",
        "size",
        "图标",
        "icon",
        "颜色",
        "color",
        "色值",
        "红色",
        "red",
        "橙色",
        "orange",
        "黄色",
        "yellow",
        "绿色",
        "green",
        "蓝色",
        "blue",
        "warning",
        "danger",
        "primary",
        "error",
        "success",
        "点击",
        "click",
        "逻辑",
        "logic",
        "保留",
        "改动",
        "修改",
        "改成",
        "改为",
        "样式",
        "style",
        "宽度",
        "width",
        "高度",
        "height",
        "这个",
        "上一",
        "一轮",
        "上轮",
        "基础",
        "同样",
        "保持",
        "一致",
        "两处",
        "应用",
        "配色",
        "写法",
        "视觉",
    }
)
#: 设计令牌证据条数上限。取 8 而非 3：主题对象通常连续定义 colorPrimary/Info/Success/
#: Warning/Error，只取前 3 会把用户真正关心的 colorError 截掉（实测目标项目 L10）。
#: pattern 扩宽后命中变多，上限同步从 5 提到 8，避免目标令牌被前几条挤掉。
_TOKEN_PROBE_LIMIT = 8

#: 设计令牌形态：AntD 主题键、任意 CSS 自定义属性、常见主题命名族。
#: 项目既可能用 JS 主题对象（AntD），也可能用 CSS 变量或 brand/bg/text 命名族，三种都要探。
_TOKEN_PROBE_PATTERNS = (
    r"color(?:Error|Primary|Warning|Success|Info|Link)\s*:",
    r"--[A-Za-z][\w-]*\s*:",
    r"(?:brand|theme|bg|text|border)[A-Z][A-Za-z0-9]*\s*:",
)
_TOKEN_PROBE_GLOB = "*.{ts,tsx,js,jsx,vue,svelte,css,less,scss}"


def _with_route(args: list[str], key: str) -> list[str]:
    """在真实 rg 参数后追加测试路由键（LocalCommandRunner 转发前过滤）。"""
    return [*args, f"--route-key={key}"]


def _is_comment_line(line: str) -> bool:
    """是否为注释行（块注释续行 / 行注释）。

    为什么必须跳过：文件头注释常是一段领域说明（如「图书管理页，管理员角色」），
    天然命中大量原句词元，会把锚点吸到第 2 行；而用户要改的代码永远不是注释。
    """
    stripped = line.strip()
    return stripped.startswith(("//", "*", "/*", "*/", "#"))


def _anchor_terms(sentence: str) -> set[str]:
    """原句词元：中文二元组 + 中英桥接词。"""
    terms = {t for t in tokenize_sentence(sentence) if t}
    terms |= {t for t in expand_zh_en(sentence) if t}
    return terms


def _window_terms(lines: list[str], index: int, terms: set[str]) -> set[str]:
    """第 ``index`` 行起（含后 ``_ANCHOR_WINDOW`` 行）命中的词元集合。"""
    window = "\n".join(lines[index - 1 : index + _ANCHOR_WINDOW]).lower()
    return {term for term in terms if term in window}


def _best_anchor(text: str, terms: set[str]) -> tuple[int, int]:
    """返回（最佳行号, 命中数）；按「本行 + 后 ``_ANCHOR_WINDOW`` 行」计命中。

    窗口是必需的：实测目标项目的「编辑」按钮写成
    ``<Button ...>`` / ``编辑`` / ``</Button>`` 三行，单行打分时每行只有 1 个词元，
    永远达不到阈值，锚点会被退回上一轮那个单行按钮。
    """
    lines = text.splitlines()
    best_line = 0
    best_hits = 0
    for index, line in enumerate(lines, start=1):
        if _is_comment_line(line):
            continue
        hits = len(_window_terms(lines, index, terms))
        if hits > best_hits:
            best_line, best_hits = index, hits
    return best_line, best_hits


def _pick_anchor_line(
    text: str, definition_line: int, sentence: str, previous_sentence: str = ""
) -> int:
    """在目标文件内选「原句最相关行」作为片段锚点；命中不足时回落 ``definition_line``。

    **为什么不能直接用 definition_line**：实测目标项目里组件声明在第 55 行，而用户要改
    的按钮在第 233 行，相差 178 行——按定义行取片段，模型根本看不到要改的那一行，
    只能编造位置。锚点因此必须由原句在文件内自行定位。

    **为什么本轮句优先**（2026-11-12）：多轮里本轮句子常只说「这个按钮」「编辑按钮」，
    依赖上一轮上下文。若把两轮词元等权合并，上一轮的「新增图书」会把锚点拉回第一个按钮，
    本轮真正要改的第二处（如「编辑」）永远进不了片段。故先只用本轮词元定位，
    达到 ``_ANCHOR_MIN_HITS`` 即采用。

    **为什么「只命中泛化词」时不采用本轮结果**：实测 R2「把这个按钮的红色改成橙色」，
    本轮词元在筛选区的「查询」按钮附近刚好命中 button/click/size 三个泛化词，锚点落到
    第 257 行，片段（242-277）里根本没有要改的「新增图书」按钮（第 233 行）；而合并
    上一轮词元后命中数更高、正落在真正目标上。故本轮窗口若识别不出任何具体元素，
    交给「本轮 ∪ 上一轮」定位；命中数不足时才回落 ``definition_line``。
    """
    lines = text.splitlines()
    current = _anchor_terms(sentence)
    if current:
        line, hits = _best_anchor(text, current)
        if line and hits >= _ANCHOR_MIN_HITS:
            identifying = _window_terms(lines, line, current) - _GENERIC_ANCHOR_TERMS
            if identifying:
                return line
    merged = current | _anchor_terms(previous_sentence)
    if not merged:
        return definition_line
    line, hits = _best_anchor(text, merged)
    return line if hits >= _ANCHOR_MIN_HITS else definition_line


def _render_excerpt(lines: list[str], anchor: int) -> str:
    """截取锚点窗口并给每行加 ``"行号| "`` 前缀；超字符上限截断并标注。"""
    if anchor <= 0 or not lines:
        return ""
    start = max(1, anchor - _EXCERPT_BEFORE)
    end = min(len(lines), anchor + _EXCERPT_AFTER)
    rendered: list[str] = []
    total = 0
    for index in range(start, end + 1):
        item = f"{index}| {lines[index - 1]}"
        if total + len(item) + 1 > _EXCERPT_MAX_CHARS:
            rendered.append("…（片段已截断）")
            break
        rendered.append(item)
        total += len(item) + 1
    return "\n".join(rendered)


def _rank_token_hits(hits: list[str], sentence: str) -> list[str]:
    """按与原句的相关性排序令牌命中（稳定排序，同分保持文件顺序）。

    为什么需要：主题对象里 colorPrimary/Info/Success/Warning/Error 是连续定义的，
    单纯截断前 N 条会稳定地把用户关心的那个颜色（如红色 → colorError）挤掉。
    用原句词元做重叠排序，零额外进程。
    """
    terms = {t for t in expand_zh_en(sentence) if t}
    # 颜色语义同族：用户说「红色」时 error/danger 都算命中，「主色」时 primary 算命中。
    family = {
        "red": ("error", "danger", "red"),
        "danger": ("error", "danger", "red"),
        "primary": ("primary",),
        "success": ("success",),
        "warning": ("warning",),
    }
    needles: set[str] = set(terms)
    for term in terms:
        needles.update(family.get(term, ()))

    def _score(hit: str) -> int:
        lowered = hit.lower()
        return sum(1 for needle in needles if needle and needle in lowered)

    return sorted(hits, key=_score, reverse=True)


async def _probe_design_tokens(
    runner: CommandRunner, root: str, sentence: str = ""
) -> tuple[str, ...]:
    """一次 rg 取项目设计令牌定义（≤5 行），按原句相关性排序后返回。

    为什么需要：四段式的第三段要回答「这个改动与项目既有色板是否一致」。没有令牌证据
    时模型只能凭印象说「红色通常叫 danger」，那是猜测；有了 ``antdTheme.ts:10`` 这样的
    命中行，方案才能给出可复核的路径与色值。
    """
    try:
        out = await runner.run(
            _with_route(
                [
                    "rg",
                    "-n",
                    *_flatten_patterns(_TOKEN_PROBE_PATTERNS),
                    "--glob",
                    _TOKEN_PROBE_GLOB,
                    ".",
                ],
                "design-tokens",
            ),
            allowed_exit_codes=_RG_ALLOWED,
            cwd=None if root in (".", "") else root,
        )
    except Exception:  # noqa: BLE001 - 令牌探测是增强项，失败不得中断主链
        return ()
    hits = [line.strip() for line in out.splitlines() if line.strip()]
    if not hits:
        return ()
    ranked = _rank_token_hits(hits, sentence) if sentence else hits
    return tuple(ranked[:_TOKEN_PROBE_LIMIT])


def _flatten_patterns(patterns: tuple[str, ...]) -> list[str]:
    """多个正则折成 rg 的 ``-e`` 序列（等价于 OR）。"""
    args: list[str] = []
    for pattern in patterns:
        args.extend(["-e", pattern])
    return args


async def locate_symbol(
    symbol: Symbol,
    runner: CommandRunner,
    reader: FileReader,
    *,
    root: str = ".",
    sentence: str = "",
    previous_sentence: str = "",
) -> CodeLocation:
    """定位符号：定义行号（rg 首个精确匹配）+ 选择器/token（读文件正则提取）。

    关联测试文件按命名约定对候选路径做存在性检查。
    root：目标项目根（Symbol.path 为仓库相对路径，FileReader 文件系统访问需拼接——
    进程 cwd 是 DevPrompt AI 自身而非目标项目，4H 端到端实测暴露）。
    sentence：原句，仅用于在文件内锚定「用户真正想改的那一行」，缺省时回落定义行。
    """

    def _fs(rel: str) -> str:
        # MUST-20：越界或非法路径返回空串，调用方按「文件不可用」处理。
        return safe_join(root, rel)

    # 1) 定义行号：rg --json 固定串搜索限定该文件
    def_args = _with_route(
        [
            "rg",
            "--json",
            "-n",
            "--no-heading",
            "--fixed-strings",
            symbol.name,
            "--glob",
            symbol.path,
            ".",
        ],
        f"def:{symbol.name}",
    )
    # cwd 必须是项目根：进程 cwd 是本工具自身仓库，`--glob 相对路径` 否则永不命中
    raw = await runner.run(
        def_args, allowed_exit_codes=_RG_ALLOWED, cwd=None if root in (".", "") else root
    )
    definition_line = _first_match_line(raw)

    # 2) 选择器与设计 token：读文件文本正则提取
    # MUST-20：越界路径 _fs 返回空串，此时不读文件（等价于文件不存在）。
    full = _fs(symbol.path)
    text = await reader.read(full) if full else ""
    selectors: list[str] = []
    for m in _CLASS_RE.finditer(text):
        for cls in m.group(1).replace("'", " ").replace('"', " ").split():
            if cls and cls not in selectors:
                selectors.append(cls)

    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        if tok not in tokens:
            tokens.append(tok)

    # 3) 关联测试文件：按命名约定对候选路径做存在性检查
    test_paths: list[str] = []
    stem, dot, ext = symbol.path.rpartition(".")
    base = stem if dot else symbol.path
    file_name = symbol.path.rsplit("/", 1)[-1]
    ext_clean = ext if dot else "ts"
    candidates = [
        f"{base}.test.{ext_clean}",
        f"{base}.spec.{ext_clean}",
        f"test_{file_name}",
        f"{base}_test.{ext_clean}",
    ]
    for cand in candidates:
        if await reader.exists(_fs(cand)):
            test_paths.append(cand)

    # 4) 目标片段（供生成层写「定位」与「实施」两段）与设计令牌证据
    lines = text.splitlines()
    anchor = _pick_anchor_line(text, definition_line, sentence, previous_sentence)
    excerpt = _render_excerpt(lines, anchor)
    token_hits = await _probe_design_tokens(runner, root, sentence)

    return CodeLocation(
        symbol_name=symbol.name,
        path=symbol.path,
        definition_line=definition_line,
        selectors=selectors,
        tokens=tokens,
        test_paths=test_paths,
        excerpt=excerpt,
        token_hits=token_hits,
    )


def _first_match_line(rg_json: str) -> int:
    """从 rg --json 输出提取首个匹配行号；无匹配返回 0（F-104 的 symbol_in_file 会标 fail）。"""
    for line in rg_json.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "match":
            ln = obj.get("data", {}).get("line_number")
            if isinstance(ln, int):
                return ln
    return 0
