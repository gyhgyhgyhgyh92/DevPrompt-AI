"""F-102 候选检索：原句词元 × 符号词元 打分排序，硬约束 ≤25 条（MUST-09）。

纯函数零 I/O；候选仅符号名+路径，类型层无正文字段。
来源通道：symbol（符号名命中）/ path（路径词元命中）。
「similarity」通道为 F-801 不达标时的重做预案（放宽匹配/模糊匹配），首版不实现——
按真源 §4.4 门禁处置：召回率 <80% 时才加强，避免过早优化。

中英映射词表（F-801 实测结论）：纯中文指称与英文标识符零词元重叠是召回缺口主因，
用通用开发/UI 领域的静态词表桥接（非编辑距离、非 LLM 扩展、零 I/O）。

F-801 真实语料预览（73/100）暴露两类缺口的通用修复：
1. 单复数归一（_normalize_term）：defaults/cookies 类词形差异导致零重叠；
2. 精确名加成（_EXACT_NAME_BONUS）：目标全名被原句整体提及时，
   与数百个仅部分词元重叠的同分符号并列，同分截断挤出不前列；
3. 滑窗扩到 5→4→3→2：下拉列表/开发者工具类复合领域词需要长窗匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from devprompt_ai.common.text import split_identifier, tokenize_sentence
from devprompt_ai.domain.models import Candidate, CandidateSource, Symbol
from devprompt_ai.domain.retrieval.bm25 import BM25Index, rrf
from devprompt_ai.domain.retrieval.salience import path_weight

#: 候选上限（2026-11-15 用户裁定 25 → 50：提升召回，减少真目标被截断的概率）。
#: 成本：排序提示词增量约 1.5-3k tokens，仍在 max_state_tokens=30000 预算内。
MAX_CANDIDATES = 50
MIN_CANDIDATES = 3  # F-102：少于 3 条触发人工指定流程

_SYMBOL_WEIGHT = 2.0
_PATH_WEIGHT = 1.0
# 精确名加成：幅度取 3.0（= 1.5 个符号名命中）。论证：
# - 下限：须让「1 个全名命中 + 加成」稳定压过「2 个部分词元命中」的纯测试符号
#   （2×2+1=5 分，是真实语料中同分截断的主力竞争者），即 bonus > 5−(2+1) = 2；
# - 上限：不得把 path-only 噪声顶进前列——path-only 候选名称必不命中，拿不到加成，
#   而拿到加成的候选至少含 1 个符号名命中（≥2 分），加成 3 后为 5 分，
#   与真实多词元命中（4~6 分）同档，不会形成断层式霸榜（mock + 真实语料回归验证）。
_EXACT_NAME_BONUS = 3.0
# 精确名加成的 DF（同名符号数）上限：全名匹配只在名字稀疏时具区分度。
# 真实符号表实测（F-801 语料）：目标侧 command=14、Context=2、$reset≈4；
# 噪声侧 cli=237、store=133、cmd=76、option=291、version=1288——
# 高频通名加全名加成会让数百同分候选霸满 25 席（MUST-09 截断），故超限不加成。
_MAX_EXACT_NAME_DF = 20

#: 直译 UI 泛词的英文词元（对齐 ZH_EN_MAP 的 UI 段）：这些词由中文（页面/按钮/样式…）
#: 机器翻译而来，不能视为「用户点名」——否则 page 这类通名会靠 +3.0 精确名加成压过真正
#: 的多词元业务符号（实测：BookListPage 6.0 < page 7.0，需求却被引到 Java 的 PageResult）。
#: 用户字面写了英文词（如「提交按钮 button」）时仍享受加成，故按 literal_terms 放行。
_GENERIC_UI_TERMS: Final[frozenset[str]] = frozenset(
    {
        "page", "ui", "interface", "home", "profile", "center", "detail", "view",
        "component", "module", "app", "entry", "main", "sidebar", "toolbar",
        "button", "input", "form", "table", "list", "modal", "dialog", "tooltip",
        "tag", "tab", "menu", "navigation", "breadcrumb", "pagination", "avatar",
        "badge", "skeleton", "screen", "placeholder", "notification", "message",
        "search", "box", "dropdown", "checkbox", "radio", "switch", "slider",
        "progress", "drawer", "popover", "carousel", "mask", "layout", "style",
        "theme", "font", "border", "radius", "shadow", "spacing", "width", "height", "line",
        "size", "opacity", "animation", "transition", "responsive", "adaptive",
        "hover", "click", "selected", "disabled", "enabled", "readonly", "highlight",
        "mobile", "desktop", "horizontal", "vertical", "fullscreen", "top", "bottom",
        "header", "footer", "zebra",
    }
)

#: 技术栈提示词（2026-11-15）：原句明确只提一侧时，同分候选优先该侧文件。
#: 跨端仓库里「前端按钮」与后端同名符号同分时，靠这一档分出胜负；两侧都提则不干预。
_FRONTEND_HINTS: Final[tuple[str, ...]] = (
    "前端", "页面", "界面", "按钮", "样式", "组件", "弹窗", "表单", "布局", "配色",
)
_BACKEND_HINTS: Final[tuple[str, ...]] = (
    "后端", "接口", "控制器", "服务", "实体", "数据库", "表结构", "事务",
    "mapper", "controller", "service",
)
_FRONTEND_SUFFIXES: Final[tuple[str, ...]] = (
    ".tsx", ".ts", ".jsx", ".js", ".vue", ".css", ".scss", ".less", ".html",
)
_BACKEND_SUFFIXES: Final[tuple[str, ...]] = (
    ".java", ".py", ".go", ".kt", ".cs", ".rb", ".php", ".sql",
    ".rs", ".swift", ".scala", ".lua", ".ex", ".dart", ".c", ".cpp", ".h",
)


def _prefer_stack(sentence: str) -> str | None:
    """原句只提一侧技术栈时返回 "front"/"back"；两侧都提或都没提返回 None。"""
    front = any(hint in sentence for hint in _FRONTEND_HINTS)
    back = any(hint in sentence.lower() for hint in _BACKEND_HINTS)
    if front == back:
        return None
    return "front" if front else "back"


def _stack_rank(symbol: Symbol, prefer: str | None) -> int:
    """同分档位：偏好栈命中取 0，其它取 1；prefer 为 None 时恒 0（退化为原行为）。"""
    if prefer is None:
        return 0
    suffixes = _FRONTEND_SUFFIXES if prefer == "front" else _BACKEND_SUFFIXES
    return 0 if symbol.path.lower().endswith(suffixes) else 1

# 连续 CJK 段（与 common.text 同一字符区间定义，避免反向依赖其私有正则）
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

# key=中文词（2~3 字），value=空格分隔的小写英文词元；纯静态通用领域词，非 mock 特例。
ZH_EN_MAP: dict[str, str] = {
    # ── 动作 · 增删改查 ──
    "创建": "create",
    "新增": "add",
    "添加": "add",
    "删除": "delete",
    "修改": "modify",
    "编辑": "edit",
    "更新": "update",
    "查询": "query",
    "查找": "find",
    "搜索": "search",
    "过滤": "filter",
    "筛选": "filter",
    "排序": "sort",
    "复制": "copy",
    "粘贴": "paste",
    "保存": "save",
    "清空": "clear",
    "重置": "reset",
    "刷新": "refresh",
    "重试": "retry",
    "导出": "export",
    "导入": "import",
    "上传": "upload",
    "下载": "download",
    # ── 动作 · 会话与确认 ──
    "登录": "login",
    "登出": "logout",
    "注销": "logout",
    "注册": "register",
    "确认": "confirm",
    "取消": "cancel",
    "关闭": "close",
    "打开": "open",
    "校验": "validate",
    "验证": "verify",
    "提交": "submit",
    # ── 动作 · 执行与交互 ──
    "执行": "execute",
    "运行": "run",
    "启动": "start",
    "加载": "loading",
    "停止": "stop",
    "暂停": "pause",
    "恢复": "resume restore",
    "展开": "expand",
    "折叠": "collapse",
    "跳转": "navigate",
    "滚动": "scroll",
    "拖拽": "drag",
    "渲染": "render",
    "解析": "parse",
    "转换": "convert",
    "计算": "calc",
    "比较": "compare",
    # ── 动作 · 工程化 ──
    "合并": "merge",
    "同步": "sync",
    "构建": "build",
    "编译": "compile",
    "部署": "deploy",
    "调试": "debug",
    "测试": "test",
    "初始化": "init",
    "安装": "install",
    "卸载": "uninstall",
    "配置": "config",
    "设置": "settings",
    "防抖": "debounce",
    "格式化": "format",
    "格式": "format",
    # ── 状态与属性 ──
    "依赖": "dependency",
    "缓存": "cache",
    "日志": "log",
    "状态": "state",
    "默认": "default",
    "全局": "global",
    "局部": "local",
    "本地": "local",
    "远程": "remote",
    "异步": "async",
    "并发": "concurrent",
    "唯一": "unique",
    "空值": "null",
    "相对": "relative",
    "倒序": "desc",
    "降序": "desc",
    "升序": "asc",
    "去重": "dedupe",
    "重复": "duplicate",
    # ── UI · 基础组件 ──
    "按钮": "button",
    "输入": "input",
    "输入框": "input",
    "表单": "form",
    "表格": "table",
    "列表": "list",
    "弹窗": "modal dialog",
    "对话框": "dialog",
    "提示": "tooltip",
    "标签": "tag",
    "标签页": "tab",
    "菜单": "menu",
    "导航": "navigation",
    "面包屑": "breadcrumb",
    "分页": "pagination",
    "头像": "avatar",
    "徽标": "badge",
    "角标": "badge",
    "骨架": "skeleton",
    "骨架屏": "skeleton screen",
    "占位": "placeholder",
    "通知": "notification",
    "消息": "message",
    "搜索框": "search box",
    "下拉": "dropdown",
    "复选": "checkbox",
    # ── UI · 控件与交互 ──
    "单选": "radio",
    "开关": "switch",
    "滑块": "slider",
    "进度": "progress",
    "抽屉": "drawer",
    "气泡": "popover",
    "轮播": "carousel",
    "遮罩": "mask",
    "悬停": "hover",
    "点击": "click",
    "选中": "selected",
    "禁用": "disabled",
    "启用": "enabled",
    "只读": "readonly",
    "高亮": "highlight",
    # ── UI · 视觉样式 ──
    "边框": "border",
    "圆角": "radius",
    "阴影": "shadow",
    "间距": "spacing",
    "宽度": "width",
    "高度": "height",
    "尺寸": "size",
    "布局": "layout",
    "样式": "style",
    "主题": "theme",
    "字体": "font",
    "行高": "line height",
    "透明度": "opacity",
    "动画": "animation",
    "过渡": "transition",
    "响应式": "responsive",
    "适配": "adaptive",
    "颜色": "color",
    "红色": "red danger",
    "主色": "primary",
    "危险": "danger",
    "背景": "background",
    # ── UI · 布局与方向 ──
    "移动端": "mobile",
    "桌面端": "desktop",
    "横向": "horizontal",
    "纵向": "vertical",
    "全屏": "fullscreen",
    "顶部": "top",
    "底部": "bottom",
    "页头": "header",
    "页脚": "footer",
    "斑马纹": "zebra",
    # ── 页面与结构 ──
    "页面": "page",
    "界面": "ui interface",
    "首页": "home",
    "主页": "home",
    "个人": "profile",
    "中心": "center",
    "详情": "detail",
    "视图": "view",
    "组件": "component",
    "模块": "module",
    "应用": "app",
    "入口": "entry main",
    "侧边栏": "sidebar",
    "工具栏": "toolbar",
    "终端": "terminal",
    # ── 文本与媒体 ──
    "语言": "language",
    "切换": "switch",
    "文本": "text",
    "标题": "title",
    "图片": "image",
    "图标": "icon",
    "显示": "display",
    "隐藏": "hide",
    "视频": "video",
    "音频": "audio",
    # ── 用户与权限 ──
    "用户": "user",
    "账号": "account",
    "密码": "password",
    "角色": "role",
    "管理员": "admin",
    "权限": "permission",
    "鉴权": "auth",
    "认证": "auth",
    "授权": "authorize",
    "令牌": "token",
    "会话": "session",
    "验证码": "captcha",
    "昵称": "nickname",
    # ── 电商领域 ──
    "商店": "shop",
    "商城": "mall",
    "购物车": "cart",
    "订单": "order",
    "商品": "product",
    "价格": "price",
    "金额": "price",
    "优惠": "discount",
    "库存": "stock",
    "支付": "pay",
    "结算": "checkout",
    "收藏": "favorite",
    "点赞": "like",
    "评价": "review",
    "评论": "comment",
    # ── 图书借阅领域 ──
    "图书": "book",
    "书籍": "book",
    # ── 数据与接口 ──
    "数据": "data",
    "模型": "model",
    "实体": "entity",
    "字段": "field",
    "参数": "param argument",
    "属性": "property",
    "变量": "variable",
    "常量": "constant",
    "类型": "type",
    "枚举": "enum choice",
    "接口": "api",
    "请求": "request",
    "响应": "response",
    "超时": "timeout",
    "重定向": "redirect",
    "异常": "exception",
    "错误": "error",
    "警告": "warning",
    "失败": "fail",
    "成功": "success",
    "完成": "complete",
    # ── 时间 ──
    "时间": "time",
    "日期": "date",
    "时区": "timezone",
    "月份": "month",
    "年份": "year",
    "时间戳": "timestamp",
    # ── 系统与环境 ──
    "版本": "version",
    "环境": "environment",
    "服务": "service",
    "服务器": "server",
    "客户": "client",
    "客户端": "client",
    "数据库": "database",
    "连接": "connection",
    "连接池": "connection pool",
    "文件": "file",
    "目录": "directory",
    "文件夹": "folder",
    "文档": "document",
    "路径": "path",
    "路由": "router",
    "前缀": "prefix",
    "中间件": "middleware",
    "拦截": "intercept",
    "网络": "network",
    "协议": "protocol",
    "域名": "domain",
    "端口": "port",
    "地址": "address",
    "链接": "link",
    "密钥": "secret key",
    "签名": "signature",
    "加密": "encrypt",
    # ── 杂项 ──
    "操作": "action",
    "命令": "command cmd",
    "工具": "util",
    "支持": "support",
    "自动": "auto",
    "补全": "completion",
    "输出": "output",
    "回车": "enter",
    "数量": "count",
    "实时": "realtime",
    "总数": "total",
    "快照": "snapshot",
    "记录": "record",
    "判断": "check",
    "检查": "check",
    "健康": "health",
    "邮箱": "email",
    "名称": "name",
    "模糊": "fuzzy",
    "货币": "currency",
    "符号": "symbol",
    "引导": "guide",
    "插画": "illustration",
    "清理": "clean",
    "统计": "stats",
    "耗时": "duration",
    "幂等": "idempotent",
    "增量": "incremental",
    "自适应": "adaptive",
    "对齐": "align",
    "表头": "header",
    "布尔": "bool",
    "退出": "exit",
    "返回": "return",
    "透传": "passthrough",
    "分区": "section",
    "常规": "general",
    "历史": "history",
    "最近": "recent",
    # ── F-801 真实语料预览缺口补映射 ──
    # 逐条分析 27 条 MISS 原句推导的通用领域词（非个案专名）：
    # 多值项为同义桥接（参数=param/argument、热更新=hmr/hot/update 等），
    # 与既有 命令→command cmd、连接池→connection pool 同一性质。
    "截断": "truncate",
    "省略号": "ellipsis",
    "文件名": "filename",
    "外部": "external outside",
    "装饰器": "decorator",
    "用法": "usage",
    "上下文": "context",
    "状态码": "status",
    "字典": "dict",
    "钩子": "hook",
    "分发": "dispatch",
    "水合": "hydrate",
    "跳过": "skip",
    "服务端": "server",
    "覆盖": "override",
    "热更新": "hmr hot update",
    "批量": "batch",
    "映射": "map",
    "后缀": "suffix",
    "获取": "get",
    "当前": "current",
    "实例": "instance",
    "告警": "warn",
    "下拉列表": "dropdown listbox",
    "进出场": "transition",
    "挂载": "mount",
    "禁止": "prevent",
    "面板": "panel",
    "摘要": "digest",
    "基本": "basic",
    "开发者工具": "devtools",
}


def expand_zh_en(sentence: str) -> list[str]:
    """将原句中的中文词经 ZH_EN_MAP 扩展为英文词元（纯函数零 I/O）。

    对每个 CJK 连续段做滑动窗口匹配：按 5→4→3→2 字窗顺序试配（长窗优先，
    支持下拉列表/开发者工具等复合领域词），命中即消费整个窗口并从窗口尾继续
    （避免重叠误配）；各窗皆未命中前进 1 字。
    返回全部英文词元（value 按空格拆分、整句去重保序）。
    """
    tokens: list[str] = []
    seen: set[str] = set()

    def _emit(value: str) -> None:
        for t in value.split():
            if t not in seen:
                seen.add(t)
                tokens.append(t)

    for run in _CJK_RUN.findall(sentence):
        i = 0
        n = len(run)
        while i < n:
            for width in (5, 4, 3, 2):
                if i + width <= n and run[i : i + width] in ZH_EN_MAP:
                    _emit(ZH_EN_MAP[run[i : i + width]])
                    i += width
                    break
            else:
                i += 1
    return tokens


def _normalize_term(term: str) -> str:
    """单复数归一：长度 >3 且以 s 结尾时去 s（defaults→default、cookies→cookie）。

    len>3 门槛避免误伤 class→clas、is→i 这类短词。
    """
    return term[:-1] if len(term) > 3 and term.endswith("s") else term


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidates: list[Candidate]
    total_matched: int
    manual_required: bool


def reorder_by_lexicon(candidates: list[Candidate], sentence: str) -> list[Candidate]:
    """I1–I3 词汇重排：BM25 名次 + 符号分名次做 RRF 融合，再乘路径权重。

    只调整顺序，**不增不减候选**（MUST-09）；单候选或空集原样返回。
    与 build_candidates 的符号打分互补：同分多候选时用字面证据二次裁决，
    测试/文档路径在同分时让位给实现文件。
    """
    if len(candidates) < 2:
        return candidates
    docs = {str(i): f"{c.name} {c.signature}".strip() for i, c in enumerate(candidates)}
    bm25_rank = BM25Index(docs).search(sentence, limit=len(candidates))
    base_rank = sorted(range(len(candidates)), key=lambda i: candidates[i].score, reverse=True)
    fused = rrf(
        [
            [str(i) for i in base_rank],
            [key for key, _score in bm25_rank],
        ]
    )
    order = sorted(
        range(len(candidates)),
        key=lambda i: fused.get(str(i), 0.0) * path_weight(candidates[i].path),
        reverse=True,
    )
    return [candidates[i] for i in order]


def _bonus_key(symbol: Symbol) -> tuple[str, str]:
    """精确名加成的两个候选键：全名归一形式 + 去 sigil 拼接形式。

    例：Defaults→(default, default)、$reset→($reset, reset)、__url__→(__url__, url)。
    第二键覆盖 $/__ 前缀符号——用户句中只写词干（$reset、__url__ 的 sigil 不入词元）。
    """
    k1 = _normalize_term(symbol.name.lower())
    k2 = _normalize_term("".join(split_identifier(symbol.name)))
    return k1, k2


def _score_symbol(
    sentence_terms: set[str],
    symbol: Symbol,
    name_df: dict[str, int],
    literal_terms: frozenset[str],
) -> tuple[float, CandidateSource, int, bool] | None:
    """词元重叠打分：符号名命中权重 2、路径词元命中权重 1；零命中返回 None。

    两侧词元先经 _normalize_term 单复数归一再求交集。
    精确名加成：符号全名的归一形式（或去 sigil 拼接形式）整体命中原句词元、
    且该名字在符号表中足够稀疏（DF ≤ _MAX_EXACT_NAME_DF）时加固定 bonus——
    全名匹配是强于部分词元重叠的信号，用于在数百同分候选中把正确目标顶入前列
    （F-801 同分截断）；高频通名不加成，避免同分群体霸满候选集。

    2026-11-15：直译 UI 泛词（page/button/style…）且用户未字面写该英文词时不给加成——
    否则「前端页面」会被译成 page 并靠 bonus 压过 BookListPage 这类多词元业务符号。
    返回 (score, source, name_hits, is_exact)，后两项供 tie-break 使用。
    """
    name_terms = {_normalize_term(t) for t in split_identifier(symbol.name)}
    name_hits = len(name_terms & sentence_terms)

    path_terms = {_normalize_term(t) for t in split_identifier(symbol.path)}
    path_hits = len(path_terms & sentence_terms)

    score = name_hits * _SYMBOL_WEIGHT + path_hits * _PATH_WEIGHT
    if score <= 0:
        return None

    is_exact = False
    for key in _bonus_key(symbol):
        if key not in sentence_terms or name_df.get(key, 0) > _MAX_EXACT_NAME_DF:
            continue
        if key in _GENERIC_UI_TERMS and key not in literal_terms:
            continue
        is_exact = True
        break
    if is_exact:
        score += _EXACT_NAME_BONUS

    source: CandidateSource = "symbol" if name_hits > 0 else "path"
    return score, source, name_hits, is_exact


def build_candidates(sentence: str, symbols: list[Symbol]) -> CandidateResult:
    """从符号表构建候选集：打分 → 降序 → 截断 25 → <3 置人工标志。"""
    # 中英映射只增词元不减（既有命中不受影响）；纯中文指称由此获得英文桥接词元；
    # 词元统一做单复数归一，两侧口径一致
    sentence_terms = {_normalize_term(t) for t in tokenize_sentence(sentence)} | {
        _normalize_term(t) for t in expand_zh_en(sentence)
    }
    # 用户字面写出的英文词元（split_identifier 只取 ASCII 段，不含中文二元组）：
    # 直译泛词靠它区分「用户点名 page」与「中文『页面』被译成 page」
    literal_terms = frozenset(_normalize_term(t) for t in split_identifier(sentence))

    # 全名 DF：统计每个加成候选键在全符号表中的出现次数（纯内存计算，零 I/O）；
    # 单 token 名两键相同，只计一次，否则 DF 被翻倍
    name_df: dict[str, int] = {}
    for sym in symbols:
        k1, k2 = _bonus_key(sym)
        name_df[k1] = name_df.get(k1, 0) + 1
        if k2 != k1:
            name_df[k2] = name_df.get(k2, 0) + 1

    scored: list[tuple[float, int, bool, Symbol]] = []
    for sym in symbols:
        hit = _score_symbol(sentence_terms, sym, name_df, literal_terms)
        if hit is None:
            continue
        score, source, name_hits, is_exact = hit
        scored.append((score, name_hits, is_exact, sym))

    # tie-break：同分时依次比 ①符号名命中数（重叠更多=证据更强）
    # ②精确名加成（全名匹配强于部分匹配）③偏好技术栈（跨端仓库只按同分档位，不改分数）
    # ④名字更短（更具体的信号，保留原序）⑤路径字典序（保证确定性，保留原序）。
    prefer = _prefer_stack(sentence)
    scored.sort(
        key=lambda t: (
            -t[0],
            -t[1],
            -t[2],
            _stack_rank(t[3], prefer),
            len(t[3].name),
            t[3].path,
        )
    )

    total_matched = len(scored)
    # 超限截断而非报错（MUST-09）
    truncated = [
        Candidate(
            name=sym.name,
            path=sym.path,
            line=sym.line,
            score=score,
            source="symbol" if name_hits > 0 else "path",
            signature=sym.signature,
        )
        for score, name_hits, _exact, sym in scored[:MAX_CANDIDATES]
    ]
    manual_required = len(truncated) < MIN_CANDIDATES
    return CandidateResult(
        candidates=truncated, total_matched=total_matched, manual_required=manual_required
    )
