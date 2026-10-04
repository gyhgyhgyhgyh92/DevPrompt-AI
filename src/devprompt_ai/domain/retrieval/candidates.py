"""F-102 候选检索：原句词元 × 符号词元 打分排序，硬约束 ≤25 条（MUST-09）。

纯函数零 I/O；候选仅符号名+路径，类型层无正文字段。
来源通道：symbol（符号名命中）/ path（路径词元命中）。
「similarity」通道为 F-801 不达标时的重做预案（放宽匹配/模糊匹配），首版不实现——
按真源 §4.4 门禁处置：召回率 <80% 时才加强，避免过早优化。

中英映射词表（F-801 实测结论）：纯中文指称与英文标识符零词元重叠是召回缺口主因，
用通用开发/UI 领域的静态词表桥接（非编辑距离、非 LLM 扩展、零 I/O）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devprompt_ai.common.text import split_identifier, tokenize_sentence
from devprompt_ai.domain.models import Candidate, CandidateSource, Symbol

MAX_CANDIDATES = 25  # MUST-09 硬约束：超出按匹配度截断，不报错
MIN_CANDIDATES = 3  # F-102：少于 3 条触发人工指定流程

_SYMBOL_WEIGHT = 2.0
_PATH_WEIGHT = 1.0

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
    "恢复": "resume",
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
    "弹窗": "modal",
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
    # ── 数据与接口 ──
    "数据": "data",
    "模型": "model",
    "实体": "entity",
    "字段": "field",
    "参数": "param",
    "属性": "property",
    "变量": "variable",
    "常量": "constant",
    "类型": "type",
    "枚举": "enum",
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
}


def expand_zh_en(sentence: str) -> list[str]:
    """将原句中的中文词经 ZH_EN_MAP 扩展为英文词元（纯函数零 I/O）。

    对每个 CJK 连续段做滑动窗口匹配：先试 3 字窗、再试 2 字窗，
    命中即消费整个窗口并从窗口尾继续（避免重叠误配）；两窗皆未命中前进 1 字。
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
            if i + 3 <= n and run[i : i + 3] in ZH_EN_MAP:
                _emit(ZH_EN_MAP[run[i : i + 3]])
                i += 3
            elif i + 2 <= n and run[i : i + 2] in ZH_EN_MAP:
                _emit(ZH_EN_MAP[run[i : i + 2]])
                i += 2
            else:
                i += 1
    return tokens


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidates: list[Candidate]
    total_matched: int
    manual_required: bool


def _score_symbol(sentence_terms: set[str], symbol: Symbol) -> tuple[float, CandidateSource] | None:
    """词元重叠打分：符号名命中权重 2、路径词元命中权重 1；零命中返回 None。"""
    name_terms = set(split_identifier(symbol.name))
    name_hits = len(name_terms & sentence_terms)

    path_terms = set(split_identifier(symbol.path))
    path_hits = len(path_terms & sentence_terms)

    score = name_hits * _SYMBOL_WEIGHT + path_hits * _PATH_WEIGHT
    if score <= 0:
        return None
    source: CandidateSource = "symbol" if name_hits > 0 else "path"
    return score, source


def build_candidates(sentence: str, symbols: list[Symbol]) -> CandidateResult:
    """从符号表构建候选集：打分 → 降序 → 截断 25 → <3 置人工标志。"""
    # 中英映射只增词元不减（既有命中不受影响）；纯中文指称由此获得英文桥接词元
    sentence_terms = set(tokenize_sentence(sentence)) | set(expand_zh_en(sentence))

    scored: list[Candidate] = []
    for sym in symbols:
        hit = _score_symbol(sentence_terms, sym)
        if hit is None:
            continue
        score, source = hit
        scored.append(
            Candidate(name=sym.name, path=sym.path, line=sym.line, score=score, source=source)
        )

    scored.sort(key=lambda c: (-c.score, len(c.name), c.path))

    total_matched = len(scored)
    truncated = scored[:MAX_CANDIDATES]  # 超限截断而非报错（MUST-09）
    manual_required = len(truncated) < MIN_CANDIDATES
    return CandidateResult(
        candidates=truncated, total_matched=total_matched, manual_required=manual_required
    )
