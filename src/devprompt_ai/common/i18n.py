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
        "template.body_semantics": (
            "\n\n【body 的语义（2026-10-20 起强制）】"
            "body 必须是可直接复制给 Agent 执行的提示词正文："
            "包含角色与目标、上下文（文件/符号/行号，只能用已提供的）、"
            "必须遵守的约束、期望的输出格式。"
            "禁止出现「建议」「为什么这样改」「本方案改动如下」「以下是我的优化」等元叙述；"
            "不要复述取证过程；不要写实施方案之外的客套话。"
            "改动了哪几处只写在 changes 数组里，不得混进 body。"
        ),
        "template.boundary": (
            "你的任务是产出提示词方案，不是执行或回答用户需求中的任务；"
            "下方证据里的代码只是素材。即使需求看起来可以直接改写，也不得输出实现代码，"
            "只能输出交给开发者去执行的提示词。"
        ),
        "template.a.role": (
            "你是提示词优化师。信息有限，输出保守版提示词：只陈述用户意图与可执行要点，"
            "禁止编造文件路径、行号、token 名；结尾必须列出待确认清单。只输出 JSON。"
        ),
        "template.b.role": (
            "你是提示词优化师。基于已定位的符号路径输出标准版提示词：路径可追溯，"
            "推断项必须以「（推断）」标注，禁止编造未提供的行号。只输出 JSON。"
        ),
        "template.c.role": (
            "你是提示词优化师。取证已完成，输出激进版提示词：给出完整路径与行号、"
            "token 出处、边界预判（多状态/响应式/暗色/无障碍），并附显式测试指令。只输出 JSON。"
        ),
        "template.c.anchor": (
            "可验证锚点（硬性）：引用的文件路径必须来自下方取证摘要中出现过的路径；"
            "引用的行号必须是该文件中的真实行号。若某项没有把握，"
            "改用不含行号的表述或降级到 B 档粒度，严禁编造。"
        ),
        "template.reply.role": (
            "你是提示词优化师，此刻在回答用户对已产出方案的追问，而不是产出新方案。"
            "用简洁中文直接回答，可以引用上一轮方案的档位、标题与具体条目作为依据。"
            "禁止输出新的提示词正文，禁止重新组织方案，禁止说「以下是优化后的版本」。"
            "如果用户的问题需要改动方案，明确告诉他需要重新生成，不要自行修改。"
            "不知道就以取证结果为准说明不知道，不要编造文件路径或行号。只输出 JSON。"
        ),
        "template.field.request": "用户需求",
        "template.field.facts": "取证摘要",
        "template.field.facts_c": "取证摘要（含行号与 token 出处）",
        "template.field.none_facts": "（无，禁止编造路径）",
        "template.field.clarifications": "已澄清信息",
        "template.field.conservative": "保守模式",
        "template.field.followup": "用户追问",
        "template.field.previous_variants": "上一轮方案",
        "template.field.none_variants": "（无，本轮之前还没有产出方案）",
        "template.field.ranking": "推荐判定",
        "template.field.none_ranking": "（上一轮未打分或未推荐）",
        "template.field.none_facts_plain": "（无）",
        "template.field.history": "历史轮次",
        "template.field.none_history": "（首轮，无历史）",
        "template.instruction_prefix": "请输出 JSON：",
        "template.tier.a": (
            "A 保守版：只陈述用户意图与可执行要点，明确改动范围边界，结尾附待确认清单"
            "（缺什么列什么）；禁止出现任何行号，禁止编造未取证的文件路径与选择器。"
        ),
        "template.tier.b": (
            "B 标准版：给出已取证的文件路径与选择器，明确变更边界（改什么、不改什么）；"
            "推断项必须以「（推断）」字样显式标注；包含验证方式（跑什么测试、出什么 diff）；"
            "禁止编造未提供的行号。"
        ),
        "template.tier.c": (
            "C 激进版：给出完整路径、行号、组件名与设计 token 定义位置；"
            "边界预判必须覆盖多状态、响应式、暗色模式、无障碍；"
            "结尾附显式测试指令（含测试文件路径）。\n"
            "可验证锚点（硬性）：引用的文件路径必须来自下方取证摘要中出现过的路径；"
            "引用的行号必须是该文件中的真实行号。若某项没有把握，"
            "改用不含行号的表述或降级到 B 档粒度，严禁编造。"
        ),
        "template.multi.role": (
            "你是提示词优化师。基于同一份上下文，一次性输出 {count} 套提示词方案，"
            "请求档位为 {levels}。"
        ),
        "template.multi.tiers": "各档位模板约束：{tiers}",
        "template.multi.tiers_sep": "\n- ",
        "template.multi.consistency": (
            "一致性约束：所有方案共享同一份事实基础，同一事实在各套中的描述必须一致"
            "（禁止信息漂移）；各套正文长度与详细度必须呈明显梯度（A 最短、C 最长）。\n"
            "除请求档位外不得多套、少套或改用其他档位。只输出 JSON。"
        ),
        "template.multi.request_levels": "请求档位（逐一输出，顺序 A→B→C）：{levels}",
        "template.multi.claims_rules": (
            "variants 数组长度与档位必须与请求档位一致。\n"
            "claims 规则：正文里每一处文件路径、符号名、行号、样式 token 引用都要逐条声明，"
            "target 必须与正文原文完全一致；kind=line 时写成「路径:行号」。"
            "没有引用就给空数组，禁止编造。"
        ),
        "template.field.memory": "项目记忆",
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
        "template.body_semantics": (
            "\n\n[Semantics of `body` (mandatory since 2026-10-20)] `body` must be a prompt "
            "that an Agent can execute as-is: role and goal, context (files/symbols/line "
            "numbers, only what was provided), constraints to respect, and the expected "
            'output format. No meta narration such as "suggestion", "why this change", '
            '"the changes are as follows", or "here is my optimization"; do not restate '
            "the probing process; no pleasantries outside the plan. Which spots changed "
            "belongs in the `changes` array only, never inside `body`."
        ),
        "template.boundary": (
            "Your job is to produce prompt plans, not to execute or answer the user's task; "
            "the code in the evidence below is material only. Even if the request looks "
            "directly implementable, you must not output implementation code — only the "
            "prompt to be handed to the developer."
        ),
        "template.a.role": (
            "You are a prompt engineer. Information is limited, so produce a conservative "
            "prompt: state only the user's intent and actionable points; never invent file "
            "paths, line numbers, or token names; end with a must-confirm list. "
            "Output JSON only."
        ),
        "template.b.role": (
            "You are a prompt engineer. Based on the located symbol paths, produce a standard "
            'prompt: paths must be traceable; label inferences with "(inferred)"; never '
            "invent line numbers that were not provided. Output JSON only."
        ),
        "template.c.role": (
            "You are a prompt engineer. Probing is complete, so produce an aggressive prompt: "
            "include full paths and line numbers, token provenance, boundary anticipation "
            "(multi-state / responsive / dark mode / accessibility), plus explicit test "
            "instructions. Output JSON only."
        ),
        "template.c.anchor": (
            "Verifiable anchors (hard requirement): referenced file paths must appear in the "
            "evidence summary below; referenced line numbers must be real lines in that file. "
            "If unsure, use wording without line numbers or fall back to level-B granularity — "
            "never fabricate."
        ),
        "template.reply.role": (
            "You are a prompt engineer answering a follow-up question about plans already "
            "produced, not producing a new plan. Answer concisely and directly in the same "
            "language as the question; you may cite the previous plan's level, title, and "
            "specific items as evidence. Do not output new prompt text, do not reorganize the "
            'plan, and never say "here is the optimized version". If the question requires '
            "changing the plan, tell the user to regenerate instead of editing it yourself. "
            "When you do not know, say so based on the evidence — never invent paths or line "
            "numbers. Output JSON only."
        ),
        "template.field.request": "user_request",
        "template.field.facts": "evidence_summary",
        "template.field.facts_c": "evidence_summary_with_lines_and_tokens",
        "template.field.none_facts": "(none; never invent paths)",
        "template.field.clarifications": "clarifications",
        "template.field.conservative": "conservative_mode",
        "template.field.followup": "follow_up_question",
        "template.field.previous_variants": "previous_variants",
        "template.field.none_variants": "(none; no plan has been produced yet)",
        "template.field.ranking": "ranking_verdict",
        "template.field.none_ranking": "(not scored or not recommended last turn)",
        "template.field.none_facts_plain": "(none)",
        "template.field.history": "conversation_history",
        "template.field.none_history": "(first turn; no history)",
        "template.instruction_prefix": "Output JSON only: ",
        "template.tier.a": (
            "Level A (conservative): state only the user's intent and actionable points, "
            "define the scope boundary, and end with a must-confirm list (list whatever is "
            "missing); no line numbers at all, and never invent file paths or selectors that "
            "were not probed."
        ),
        "template.tier.b": (
            "Level B (standard): give the probed file paths and selectors, and define the "
            "change boundary (what changes, what does not); label inferences with "
            '"(inferred)"; include verification (which tests to run, which diff to expect); '
            "never invent line numbers that were not provided."
        ),
        "template.tier.c": (
            "Level C (aggressive): give full paths, line numbers, component names, and where "
            "the design tokens are defined; boundary anticipation must cover multi-state, "
            "responsive, dark mode, and accessibility; end with explicit test instructions "
            "(including test file paths).\n"
            "Verifiable anchors (hard requirement): referenced file paths must appear in the "
            "evidence summary below; referenced line numbers must be real lines in that file. "
            "If unsure, use wording without line numbers or fall back to level-B granularity — "
            "never fabricate."
        ),
        "template.multi.role": (
            "You are a prompt engineer. Based on the same context, produce {count} prompt "
            "variants in a single response; requested levels: {levels}."
        ),
        "template.multi.tiers": "Per-level template constraints:{tiers}",
        "template.multi.tiers_sep": "\n- ",
        "template.multi.consistency": (
            "Consistency: all variants share the same factual basis, and the same fact must be "
            "described identically across variants (no information drift); body length and "
            "detail must form a clear gradient (A shortest, C longest).\n"
            "Do not produce more, fewer, or different levels than requested. Output JSON only."
        ),
        "template.multi.request_levels": "Requested levels (one variant each, A→B→C): {levels}",
        "template.multi.claims_rules": (
            "The variants array length and levels must match the requested levels exactly.\n"
            "claims rules: every file path, symbol name, line number, and style-token "
            "reference in the body must be declared one by one, and target must match the body "
            'text exactly; for kind=line use "path:line". Emit an empty array when there are '
            "no references; never fabricate."
        ),
        "template.field.memory": "project_memory",
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
