"""后端静态文案的本地化（2026-11-06，F-209 后端双语）。

为什么放 ``common/``：文案表是纯数据、``tr`` 是纯查表，不含任何业务判定；``domain/``
与 ``service`` 都可 import（与 ``common.text`` 同类先例，MUST-06），HTTP 层只负责把
``Accept-Language`` 解析成 ``Locale`` 再往下传。

约定：
- 键用扁平点号前缀（``progress.symbols`` / ``gate.red.no_target``），按模块分组；
- 只放静态文本，**禁止**拼用户原句或绝对路径（MUST-19）；
- 缺键返回键名本身，便于测试暴露漏译，不抛异常打断交付。
"""

from __future__ import annotations

from typing import Final, Literal

Locale = Literal["zh-CN", "en"]

DEFAULT_LOCALE: Final[Locale] = "zh-CN"

#: 两语言键集必须完全一致，由 tests/test_i18n.py 强制。
MESSAGES: Final[dict[str, dict[str, str]]] = {
    "zh-CN": {
        "progress.retrieval": "正在检索相关代码…",
        "progress.symbols": "已扫描 {total} 个符号",
        "progress.candidates": "筛选出 {count} 个候选组件",
        "progress.facts": "已核对 {count} 项取证结论",
        "progress.target": "已定位目标：{label}",
        "progress.level": "将生成 {level} 档提示词",
        "progress.clarification": "需要向你确认 {count} 个问题",
        "progress.generation": "正在生成提示词…",
        "progress.scoring": "正在评估方案适配度…",
        "progress.recommendation": "已标出推荐方案：{label}",
        "progress.single_variant": "只生成一套方案（信息已足够），跳过打分与推荐。",
        "progress.answering": "正在回答你的问题…",
        "progress.manual_required": "未能自动定位，请手动补充组件名或文件路径。",
        "progress.stop_generation": "已停止生成。",
        "progress.done": "已完成。",
    },
    "en": {
        "progress.retrieval": "Retrieving related code…",
        "progress.symbols": "{total} symbols scanned",
        "progress.candidates": "{count} candidate components selected",
        "progress.facts": "{count} fact checks verified",
        "progress.target": "Target located: {label}",
        "progress.level": "Generating level {level} prompts",
        "progress.clarification": "{count} questions need your confirmation",
        "progress.generation": "Generating prompts…",
        "progress.scoring": "Scoring variant fit…",
        "progress.recommendation": "Recommended variant marked: {label}",
        "progress.single_variant": "Only one variant was needed; scoring and ranking skipped.",
        "progress.answering": "Answering your question…",
        "progress.manual_required": (
            "Could not locate the target; please add a component name or file path."
        ),
        "progress.stop_generation": "Generation stopped.",
        "progress.done": "Done.",
    },
}


def resolve_locale(raw: str | None) -> Locale:
    """``Accept-Language`` → :data:`Locale`。

    取首个语言标签（忽略 ``q=`` 权重），``en*`` 视为英文，其余（含空值、垃圾值）
    一律回落 ``zh-CN``——未知输入不应导致报错，也不应把界面变成第三种语言。
    """
    if not raw:
        return DEFAULT_LOCALE
    first = raw.split(",", 1)[0].split(";", 1)[0].strip().lower()
    return "en" if first.startswith("en") else DEFAULT_LOCALE


def tr(key: str, locale: Locale = DEFAULT_LOCALE, **params: object) -> str:
    """查表并插值；缺键或插值参数不匹配时返回模板原文（不抛异常）。"""
    table = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = table.get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LOCALE].get(key)
    if template is None:
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template
