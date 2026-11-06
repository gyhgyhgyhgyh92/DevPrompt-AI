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
        "progress.retrieval": "开始分析这条提示词，先在你的项目里检索相关代码。",
        "progress.symbols": "符号表就绪，共 {total} 个符号参与匹配。",
        "progress.candidates_trimmed": (
            "匹配到 {matched} 个相关符号，按相关度压到 {kept} 条候选（上限固定）。"
        ),
        "progress.candidates_all": "匹配到 {matched} 个相关符号，全部进入候选（未触及上限）。",
        "progress.manual_required": (
            "只匹配到 {matched} 个符号，不足以自动定位目标，"
            "需要你补充具体符号名或文件路径后再继续。"
        ),
        "progress.target": "选中目标 {name}（{location}），正在核对事实依据。",
        "progress.facts": "事实核对完成：{total} 项中 {passed} 项通过。",
        "progress.level": "研判完成，整体置信度 {confidence}，可输出 {level} 档。",
        "progress.level_unknown": "未评估",
        "progress.clarification": "研判出 {count} 处信息缺口，先和你确认再继续。",
        "progress.answering": "正在回答你的追问。",
        "progress.generation": "开始生成 {count} 套方案（{labels}）。",
        "progress.single_variant": "信息量只够输出 1 套保守方案，按规则跳过打分与推荐。",
        "progress.scoring": "为各套方案打分，并结合你的历史偏好计算加权总分。",
        "progress.recommendation_unmarked": (
            "综合评分完成，{reason}（最高为 {label} 档，领先 {gap}）。"
        ),
        "progress.recommendation_plain": "综合评分完成，推荐 {label} 档（领先次优 {gap}）。",
        "progress.recommendation_reasoned": (
            "综合评分完成，推荐 {label} 档（领先 {gap}，{reason}）。"
        ),
        "level.a": "保守",
        "level.b": "标准",
        "level.c": "激进",
        "common.list_sep": "、",
        "clarify.manual_reason": "候选不足（{matched} 条）",
        "clarify.manual_ask": "请指明目标符号名与文件路径（格式：符号@路径）",
        "gate.red.no_target": "未定位到目标符号",
        "gate.red.facts_failed": "适用事实全部未通过",
        "gate.red.claims_undeclared": "方案未声明任何引用，证据链无法核对",
        "gate.red.anchor_invalid": "C 档方案含 {count} 处无效锚点（路径不存在或行号越界）",
        "gate.disclosure.red": (
            "本轮证据链不足以背书，方案照常提供，但未标记为可交付档位：{reasons}。"
        ),
        "gate.yellow.coverage": "断言覆盖率 {coverage}，低于 {threshold}",
        "gate.yellow.variant_short": "本次仅 {count} 套（模型未给出全部档位）",
        "gate.yellow.single_variant": "仅一套方案，未做推荐比较",
        "gate.yellow.no_recommend": "推荐置信度不足",
        "gate.disclosure.yellow": "本轮证据可用但不足以背书推荐，方案照常提供：{reasons}。",
        "ranking.conf_base": "置信度不足，建议人工选择",
        "ranking.conf_close": "三套适配度接近，建议人工选择",
        "ranking.conf_small_gap": "分差较小",
        "ranking.conf_top": "{base}（最高档 {conf} < {min}）",
        "ranking.conf_any": "{base}（最低档 {conf} < {min}）",
        "ranking.need_two": "推荐判定需要至少 2 套方案（MUST-28），实际 {count}",
    },
    "en": {
        "progress.retrieval": (
            "Analyzing this prompt; first retrieving related code from your project."
        ),
        "progress.symbols": "Symbol table ready: {total} symbols are matched.",
        "progress.candidates_trimmed": (
            "Matched {matched} related symbols; kept {kept} candidates by relevance (fixed cap)."
        ),
        "progress.candidates_all": (
            "Matched {matched} related symbols; all of them entered the candidates (cap not hit)."
        ),
        "progress.manual_required": (
            "Only {matched} symbols matched, which is not enough to locate the target "
            "automatically; please add a specific symbol name or file path to continue."
        ),
        "progress.target": (
            "Target selected: {name} ({location}); verifying the supporting facts."
        ),
        "progress.facts": "Fact checks finished: {passed} of {total} passed.",
        "progress.level": (
            "Probing finished; overall confidence {confidence}, level {level} can be produced."
        ),
        "progress.level_unknown": "not assessed",
        "progress.clarification": (
            "Found {count} information gaps; confirming them with you before continuing."
        ),
        "progress.answering": "Answering your follow-up question.",
        "progress.generation": "Generating {count} variants ({labels}).",
        "progress.single_variant": (
            "There is only enough information for one conservative variant; "
            "scoring and ranking are skipped by rule."
        ),
        "progress.scoring": (
            "Scoring each variant and computing a weighted total with your historical preferences."
        ),
        "progress.recommendation_unmarked": (
            "Scoring finished; {reason} (best is level {label}, ahead by {gap})."
        ),
        "progress.recommendation_plain": (
            "Scoring finished; recommending level {label} (ahead of runner-up by {gap})."
        ),
        "progress.recommendation_reasoned": (
            "Scoring finished; recommending level {label} (ahead by {gap}, {reason})."
        ),
        "level.a": "conservative",
        "level.b": "standard",
        "level.c": "aggressive",
        "common.list_sep": ", ",
        "clarify.manual_reason": "Not enough candidates ({matched} matched)",
        "clarify.manual_ask": (
            "Please specify the target symbol and file path (format: symbol@path)"
        ),
        "gate.red.no_target": "Target symbol not located",
        "gate.red.facts_failed": "Every applicable fact check failed",
        "gate.red.claims_undeclared": (
            "The variants declare no references, so the evidence chain cannot be verified"
        ),
        "gate.red.anchor_invalid": (
            "Level-C variants contain {count} invalid anchor(s) (missing path or line out of range)"
        ),
        "gate.disclosure.red": (
            "Evidence is not strong enough to endorse this turn; variants are still "
            "provided, but no deliverable level is marked: {reasons}."
        ),
        "gate.yellow.coverage": ("Claim coverage {coverage} is below the required {threshold}"),
        "gate.yellow.variant_short": (
            "Only {count} variant(s) this turn (the model did not provide all levels)"
        ),
        "gate.yellow.single_variant": (
            "Only one variant, so no recommendation comparison was made"
        ),
        "gate.yellow.no_recommend": "Recommendation confidence is too low",
        "gate.disclosure.yellow": (
            "Evidence is usable but not enough to endorse a recommendation; "
            "variants are still provided: {reasons}."
        ),
        "ranking.conf_base": "Confidence is too low; please choose manually",
        "ranking.conf_close": "The three variants fit similarly; please choose manually",
        "ranking.conf_small_gap": "The gap between variants is small",
        "ranking.conf_top": "{base} (top {conf} < {min})",
        "ranking.conf_any": "{base} (lowest {conf} < {min})",
        "ranking.need_two": ("Recommendation needs at least 2 variants (MUST-28); got {count}"),
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
